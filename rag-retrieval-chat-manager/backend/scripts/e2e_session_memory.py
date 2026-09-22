"""End-to-end check for session-scoped pipeline memory.

Creates its own pipeline, runs a real session against the live stores, then ends
the session and deletes the pipeline in a ``finally`` block. Safe to re-run.

    uv run python scripts/e2e_session_memory.py

The ingestion API must be on 8007, the retrieval API on 8001 and Redis on 6379.
Every URL comes from the retrieval ``Settings``, so the same env the API uses
drives this.

What it proves, in order: the assistant reports whether it has memory, a turn is
remembered, a follow-up is rewritten into a standalone question before retrieval,
a second session stays isolated, the stream path remembers too, the OpenAI route
continues a session, ending the session really removes the Redis key, and ending
it twice is still 204.
"""

from __future__ import annotations

import json
import sys
import uuid

import httpx

from rag_core.assistant import session_memory_for_product
from rag_shared.config import Settings

RUN_TAG = uuid.uuid4().hex[:6]
PIPELINE_NAME = f"E2E Session Assistant {RUN_TAG}"
PIPELINE_DESCRIPTION = f"Exercises session memory. Run {RUN_TAG}."

# A question and a follow-up whose meaning depends on the first. The second must be
# rewritten, because "that" alone cannot be searched for.
FIRST_QUESTION = "What is this document about?"
FOLLOW_UP = "Tell me more about that."

TRACE: list[str] = []
FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    TRACE.append(f"{'PASS' if ok else 'FAIL'} {label}{(' — ' + detail) if detail else ''}")
    print(TRACE[-1], flush=True)
    if not ok:
        FAILURES.append(label)


class Api:
    """Fails loudly instead of returning a mock, so a down service is visible."""

    def __init__(self, settings: Settings) -> None:
        self.ingestion = settings.ingestion_service_url.rstrip("/")
        self.retrieval = f"http://localhost:{settings.api_port}"
        self.headers = {"X-API-Key": settings.api_key} if settings.api_key else {}
        self.client = httpx.Client(timeout=300.0, headers=self.headers)

    def request(self, method: str, url: str, body: dict | None = None) -> tuple[int, object]:
        response = self.client.request(method, url, json=body)
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
        return response.status_code, payload

    def ingestion_call(self, method: str, path: str, body: dict | None = None):
        return self.request(method, f"{self.ingestion}{path}", body)

    def retrieval_call(self, method: str, path: str, body: dict | None = None):
        return self.request(method, f"{self.retrieval}{path}", body)

    def stream(self, path: str, body: dict) -> list[dict]:
        frames: list[dict] = []
        with self.client.stream("POST", f"{self.retrieval}{path}", json=body) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw or raw == "[DONE]":
                    continue
                try:
                    frames.append(json.loads(raw))
                except json.JSONDecodeError:
                    continue
        return frames


def pick_product(api: Api) -> dict | None:
    """A product that can both answer (a retrieval destination) and remember (Redis)."""
    status, products = api.ingestion_call("GET", "/api/knowledge-products")
    if status != 200 or not isinstance(products, list):
        return None
    for product in products:
        destinations = product.get("destinations") or []
        enabled = {d.get("destination_type") for d in destinations if d.get("enabled")}
        if "vector_qdrant" in enabled and "cache_redisvl" in enabled:
            return product
    return None


def main() -> int:
    settings = Settings()
    api = Api(settings)
    redis_client = __import__("redis").Redis.from_url(settings.redis_url, decode_responses=True)

    product = pick_product(api)
    if product is None:
        print("No Knowledge Product has both a vector destination and Redis enabled.")
        print("Enable the Redis destination on one in the Ingestion Manager, then re-run.")
        return 1
    print(f"product: {product['name']} ({product['id']})", flush=True)

    redis_prefix = next(
        d["config"]["index_prefix"]
        for d in product["destinations"]
        if d.get("destination_type") == "cache_redisvl" and d.get("enabled")
    )
    print(f"redis prefix: {redis_prefix}", flush=True)

    pipeline_id: str | None = None
    slug: str | None = None
    sessions: list[uuid.UUID] = []

    try:
        # ── 1. A pipeline over the product ──────────────────────────────────
        status, pipeline = api.ingestion_call(
            "POST",
            "/api/pipelines",
            {
                "name": PIPELINE_NAME,
                "description": PIPELINE_DESCRIPTION,
                "knowledge_product_id": product["id"],
                "rag_strategy": "vector",
                "chat_model": "Gpt-oss-20b",
                "embedding_model": product.get("text_embedding_model") or "nvidia-embed-textonly",
            },
        )
        if status not in (200, 201):
            check("1 pipeline created", False, f"HTTP {status} {pipeline}")
            return 1
        pipeline_id = pipeline["id"]
        slug = pipeline.get("slug")
        check("1 pipeline created", bool(slug), f"slug={slug}")
        if not slug:
            return 1

        # ── 2. The assistant advertises its memory ──────────────────────────
        status, info = api.retrieval_call("GET", f"/api/assistants/{slug}")
        memory_info = (info or {}).get("session_memory") or {}
        check(
            "2 assistant reports session memory enabled",
            status == 200 and memory_info.get("enabled") is True,
            f"HTTP {status} {memory_info}",
        )
        check(
            "2 endpoints name the session routes",
            (info.get("endpoints") or {}).get("session_end") is not None,
            str((info or {}).get("endpoints")),
        )

        # ── 3. Turn one starts a session ────────────────────────────────────
        session = uuid.uuid4()
        sessions.append(session)
        status, first = api.retrieval_call(
            "POST",
            f"/api/assistants/{slug}/chat",
            {"query": FIRST_QUESTION, "session_id": str(session)},
        )
        check("3 first turn answered", status == 200, f"HTTP {status} {str(first)[:200]}")
        if status != 200:
            return 1
        check("3 session id echoed", str(first.get("session_id")) == str(session), str(first.get("session_id")))
        check(
            "3 no rewrite without history",
            first.get("effective_query") is None,
            str(first.get("effective_query")),
        )

        key = f"{redis_prefix}:memory:{session}"
        check("3 redis key written", redis_client.exists(key) == 1)
        check("3 redis key has a ttl", redis_client.ttl(key) > 0, f"ttl={redis_client.ttl(key)}")

        # ── 4. The session endpoint reports it ──────────────────────────────
        status, report = api.retrieval_call("GET", f"/api/assistants/{slug}/sessions/{session}")
        check(
            "4 session reports the exchange",
            status == 200 and report.get("exists") is True and report.get("turns") == 2,
            f"HTTP {status} {report}",
        )

        # ── 5. The follow-up is rewritten for retrieval ─────────────────────
        status, second = api.retrieval_call(
            "POST",
            f"/api/assistants/{slug}/chat",
            {"query": FOLLOW_UP, "session_id": str(session)},
        )
        check("5 follow-up answered", status == 200, f"HTTP {status} {str(second)[:200]}")
        effective = (second or {}).get("effective_query")
        check(
            "5 follow-up rewritten into a standalone question",
            bool(effective) and effective != FOLLOW_UP,
            f"effective={effective!r}",
        )

        status, report = api.retrieval_call("GET", f"/api/assistants/{slug}/sessions/{session}")
        check("5 memory grew to two exchanges", report.get("turns") == 4, str(report.get("turns")))

        # ── 6. A second session is isolated ─────────────────────────────────
        other = uuid.uuid4()
        sessions.append(other)
        status, _ = api.retrieval_call(
            "POST",
            f"/api/assistants/{slug}/chat",
            {"query": FIRST_QUESTION, "session_id": str(other)},
        )
        status, other_report = api.retrieval_call("GET", f"/api/assistants/{slug}/sessions/{other}")
        check("6 second session has only its own turns", other_report.get("turns") == 2, str(other_report.get("turns")))
        status, report = api.retrieval_call("GET", f"/api/assistants/{slug}/sessions/{session}")
        check("6 first session untouched by the second", report.get("turns") == 4, str(report.get("turns")))

        # ── 7. The stream path remembers too ────────────────────────────────
        streamed = uuid.uuid4()
        sessions.append(streamed)
        frames = api.stream(
            f"/api/assistants/{slug}/chat/stream",
            {"query": FIRST_QUESTION, "session_id": str(streamed)},
        )
        session_frames = [f for f in frames if f.get("type") == "session"]
        done = [f for f in frames if f.get("type") == "done"]
        check("7 stream emitted a session frame", bool(session_frames), f"{len(frames)} frames")
        check(
            "7 stream session frame carries the id",
            bool(session_frames) and session_frames[-1].get("session_id") == str(streamed),
            str(session_frames[-1] if session_frames else None),
        )
        status, stream_report = api.retrieval_call("GET", f"/api/assistants/{slug}/sessions/{streamed}")
        check("7 streamed turn was remembered", stream_report.get("turns") == 2, str(stream_report.get("turns")))
        check(
            "7 stream done frame carries the answer",
            bool(done) and bool((done[-1].get("metadata") or {}).get("answer")),
            f"{len(done)} done frames",
        )

        # ── 8. The OpenAI route continues a session ─────────────────────────
        openai_session = uuid.uuid4()
        sessions.append(openai_session)
        status, completion = api.retrieval_call(
            "POST",
            f"/v1/assistants/{slug}/chat/completions",
            {
                "model": "assistant",
                "messages": [{"role": "user", "content": FIRST_QUESTION}],
                "session_id": str(openai_session),
            },
        )
        check(
            "8 openai route honours session_id",
            status == 200 and str((completion or {}).get("session_id")) == str(openai_session),
            f"HTTP {status} {str(completion)[:160]}",
        )
        status, openai_report = api.retrieval_call(
            "GET", f"/api/assistants/{slug}/sessions/{openai_session}"
        )
        check("8 openai turn was remembered", openai_report.get("turns") == 2, str(openai_report.get("turns")))

        status, body = api.retrieval_call(
            "POST",
            f"/v1/assistants/{slug}/chat/completions",
            {
                "model": "assistant",
                "messages": [{"role": "user", "content": "hi"}],
                "session_id": "not-a-uuid",
            },
        )
        code = (body.get("detail") or {}).get("code") if isinstance(body, dict) else None
        check("8 a bad session_id is rejected", status == 422 and code == "INVALID_SESSION_ID", f"HTTP {status} {code}")

        status, body = api.retrieval_call(
            "POST",
            f"/v1/assistants/{slug}/chat/completions",
            {
                "model": "assistant",
                "messages": [{"role": "user", "content": FIRST_QUESTION}],
                "user": "not-a-uuid-either",
            },
        )
        check("8 a non-uuid user is ignored, not rejected", status == 200, f"HTTP {status}")

        # ── 9. Ending the session clears it ─────────────────────────────────
        status, body = api.retrieval_call("DELETE", f"/api/assistants/{slug}/sessions/{session}")
        check("9 end session answers 204", status == 204, f"HTTP {status} {body}")
        check("9 redis key is gone", redis_client.exists(key) == 0)

        status, report = api.retrieval_call("GET", f"/api/assistants/{slug}/sessions/{session}")
        check(
            "9 session reads empty after the end",
            status == 200 and report.get("exists") is False and report.get("turns") == 0,
            str(report),
        )

        status, _ = api.retrieval_call("DELETE", f"/api/assistants/{slug}/sessions/{session}")
        check("9 ending twice is still 204", status == 204, f"HTTP {status}")

        status, _ = api.retrieval_call("DELETE", f"/api/assistants/{slug}/sessions/{uuid.uuid4()}")
        check("9 ending an unknown session is 204", status == 204, f"HTTP {status}")

        # ── 10. The gate is the product's Redis destination ─────────────────
        check(
            "10 no Redis destination means no memory",
            session_memory_for_product([]) is None,
        )
        check(
            "10 a disabled Redis destination means no memory",
            session_memory_for_product(
                [
                    {
                        "destination_type": "cache_redisvl",
                        "enabled": False,
                        "config": {"index_prefix": "kp:x:00000000"},
                    }
                ]
            )
            is None,
        )
        check(
            "10 an enabled Redis destination yields prefix and ttl",
            session_memory_for_product(
                [
                    {
                        "destination_type": "cache_redisvl",
                        "enabled": True,
                        "config": {"index_prefix": "kp:x:00000000", "ttl_seconds": 3600},
                    }
                ]
            )
            == ("kp:x:00000000", 3600),
        )

    finally:
        for session in sessions:
            try:
                redis_client.delete(f"{redis_prefix}:memory:{session}")
            except Exception:  # noqa: BLE001
                pass
        if pipeline_id:
            status, _ = api.ingestion_call("DELETE", f"/api/pipelines/{pipeline_id}")
            print(f"cleanup: pipeline delete HTTP {status}", flush=True)

    print()
    passed = sum(1 for line in TRACE if line.startswith("PASS"))
    print(f"{passed}/{len(TRACE)} checks passed")
    if FAILURES:
        print("failed: " + ", ".join(FAILURES))
    return 0 if not FAILURES else 1


if __name__ == "__main__":
    sys.exit(main())
