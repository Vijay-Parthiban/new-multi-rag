"""End-to-end check for knowledge-product-backed chat assistants.

Creates its own fixtures and deletes them in a ``finally`` block, so it is safe
to re-run. Run from rag-retrieval-chat-manager/backend against the live stack:

    uv run python scripts/e2e_assistant_pipelines.py

The ingestion API must be on 8007 and the retrieval API on 8001. Ports and URLs
come from the retrieval ``Settings``, so the same env the API uses drives this.
"""

from __future__ import annotations

import json
import sys
import uuid

import httpx

from rag_shared.config import Settings

# Pipeline name and description are both unique in the ingestion database, and a
# prompt template name is unique too, so every fixture carries a per-run tag.
# Without it a re-run after a failed cleanup collides with the leftover row.
RUN_TAG = uuid.uuid4().hex[:6]
TEMPLATE_NAME = f"E2E Underwriter {RUN_TAG}"
SHORT_TEMPLATE_NAME = f"E2E One Word {RUN_TAG}"
GUARDRAILS_NAME = f"E2E Ban Classified {RUN_TAG}"
PIPELINE_NAME = f"E2E Resume Assistant {RUN_TAG}"
PIPELINE_DESCRIPTION = f"Answers questions about the resumes in the store. Run {RUN_TAG}."
CHAT_MODEL = "Gpt-oss-120b"

QUESTION = "What award did Rohan receive at Amazon?"
BANNED_PHRASE = "classified"

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

    def stream(self, path: str, body: dict) -> list[str]:
        frames: list[str] = []
        with self.client.stream("POST", f"{self.retrieval}{path}", json=body) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line.startswith("data:"):
                    frames.append(line[5:].strip())
        return frames


def pick_product(api: Api) -> dict:
    """The first product an assistant can read. Prefers the full four stores."""
    status, products = api.ingestion_call("GET", "/api/knowledge-products")
    if status != 200 or not isinstance(products, list):
        raise SystemExit(f"Cannot list knowledge products: HTTP {status} {products}")
    if not products:
        raise SystemExit("No knowledge product exists. Create one in the Ingestion Manager.")

    def retrieval_stores(product: dict) -> list[str]:
        return [
            d["destination_type"]
            for d in product.get("destinations") or []
            if d.get("enabled")
            and d["destination_type"]
            in ("vector_qdrant", "lexical_opensearch", "relational_pgvector")
        ]

    products.sort(key=lambda p: len(retrieval_stores(p)), reverse=True)
    product = products[0]
    stores = retrieval_stores(product)
    if len(stores) < 3:
        raise SystemExit(
            f"Product '{product['name']}' enables only {stores}. "
            "The check needs Qdrant, OpenSearch and PostgreSQL enabled."
        )
    return product


def main() -> int:
    settings = Settings()
    api = Api(settings)
    product = pick_product(api)
    print(f"product: {product['name']} ({product['id']})", flush=True)

    created: dict[str, list[tuple[str, str]]] = {"pipelines": [], "templates": [], "guardrails": []}

    try:
        # ── 1. Prompt template create ───────────────────────────────────────
        status, template = api.retrieval_call(
            "POST",
            "/prompt-templates",
            {
                "name": TEMPLATE_NAME,
                "description": "Created by the end-to-end check.",
                "content": (
                    "You are an underwriting assistant. Answer only from the resume "
                    "passages and reply in one short paragraph."
                ),
            },
        )
        check("1 template created", status == 201, f"HTTP {status} {template}")
        if status != 201:
            return 1
        template_id = template["id"]
        created["templates"].append((template_id, TEMPLATE_NAME))

        status, listing = api.retrieval_call("GET", "/prompt-templates")
        names = [t["name"] for t in (listing.get("items") or [])]
        check("1 template listed", status == 200 and TEMPLATE_NAME in names)

        # ── 2. Duplicate name rejected ──────────────────────────────────────
        status, body = api.retrieval_call(
            "POST", "/prompt-templates", {"name": TEMPLATE_NAME, "content": "duplicate"}
        )
        code = (body.get("detail") or {}).get("code") if isinstance(body, dict) else None
        check("2 duplicate name rejected", status == 409 and code == "PROMPT_TEMPLATE_NAME_TAKEN", f"HTTP {status} {code}")

        # A second template whose instruction is observable in the answer.
        status, short_template = api.retrieval_call(
            "POST",
            "/prompt-templates",
            {
                "name": SHORT_TEMPLATE_NAME,
                "description": "Force a one-word answer.",
                "content": "Answer in exactly one word. Do not use a full sentence.",
            },
        )
        check("2b second template created", status == 201, f"HTTP {status}")
        short_template_id = short_template["id"] if status == 201 else None
        if short_template_id:
            created["templates"].append((short_template_id, SHORT_TEMPLATE_NAME))

        # ── 3. Guardrails config ────────────────────────────────────────────
        status, guardrails = api.retrieval_call(
            "POST",
            "/guardrails/configs",
            {
                "name": GUARDRAILS_NAME,
                "description": "Created by the end-to-end check.",
                "guards": ["ban_list"],
                "mode": "both",
                "settings": {"banned_words": [BANNED_PHRASE]},
            },
        )
        check("3 guardrails config created", status == 201, f"HTTP {status} {guardrails}")
        if status != 201:
            return 1
        guardrails_id = guardrails["id"]
        created["guardrails"].append((guardrails_id, GUARDRAILS_NAME))

        # ── 4. Assistant pipeline ───────────────────────────────────────────
        status, pipeline = api.ingestion_call(
            "POST",
            "/api/pipelines",
            {
                "name": PIPELINE_NAME,
                "description": PIPELINE_DESCRIPTION,
                "knowledge_product_id": product["id"],
                "rag_strategy": "hybrid",
                "chat_model": CHAT_MODEL,
                "embedding_model": product.get("text_embedding_model") or "nvidia-embed-textonly",
                "prompt_template_id": template_id,
                "guardrails_config_id": guardrails_id,
            },
        )
        check("4 pipeline created", status == 201, f"HTTP {status} {pipeline}")
        if status != 201:
            print(json.dumps(pipeline, indent=2)[:800])
            return 1
        pipeline_id = pipeline["id"]
        slug = pipeline.get("slug")
        created["pipelines"].append((pipeline_id, PIPELINE_NAME))
        check("4 slug assigned", bool(slug), f"slug={slug}")
        destinations = (pipeline.get("knowledge_product") or {}).get("destinations") or []
        check("4 destinations in payload", len(destinations) == 4, f"{len(destinations)} entries")

        status, resolved = api.retrieval_call("GET", f"/api/assistants/{slug}")
        check("5 assistant resolved", status == 200, f"HTTP {status}")
        if status != 200:
            return 1
        strategies = [s["id"] for s in resolved["strategies_available"]]
        check(
            "5 four strategies available",
            strategies == ["vector", "lexical", "relational", "hybrid"],
            str(strategies),
        )
        stores = resolved["stores"]
        check(
            "5 stores match the product",
            stores["qdrant_collection"] == stores["opensearch_index"] == stores["pg_schema"],
            json.dumps(stores),
        )

        # ── 6. Answer over the native endpoint ──────────────────────────────
        status, answer = api.retrieval_call(
            "POST", f"/api/assistants/{slug}/chat", {"query": QUESTION}
        )
        text = (answer.get("answer") or "") if isinstance(answer, dict) else ""
        sources = (answer.get("sources") or []) if isinstance(answer, dict) else []
        check("6 native chat answers", status == 200 and len(text) > 20, f"HTTP {status}")
        check("6 answer mentions the award", "award" in text.lower(), text[:120])
        check("6 sources returned", len(sources) > 0, f"{len(sources)} sources")

        # ── 7. OpenAI-compatible, non-streaming ─────────────────────────────
        openai_body = {
            "model": "assistant",
            "messages": [{"role": "user", "content": QUESTION}],
        }
        status, completion = api.retrieval_call(
            "POST", f"/v1/assistants/{slug}/chat/completions", openai_body
        )
        content = ""
        if isinstance(completion, dict):
            content = (completion.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        check(
            "7 OpenAI completion shape",
            status == 200 and isinstance(completion, dict) and completion.get("object") == "chat.completion",
            f"HTTP {status}",
        )
        check("7 OpenAI completion content", len(content) > 20, content[:120])

        # ── 8. OpenAI-compatible, streaming ────────────────────────────────
        frames = api.stream(
            f"/v1/assistants/{slug}/chat/completions", {**openai_body, "stream": True}
        )
        objects = []
        for frame in frames:
            if frame == "[DONE]":
                continue
            try:
                objects.append(json.loads(frame).get("object"))
            except json.JSONDecodeError:
                objects.append(None)
        check(
            "8 OpenAI stream frames",
            bool(frames) and frames[-1] == "[DONE]" and "chat.completion.chunk" in objects,
            f"{len(frames)} frames, last={frames[-1] if frames else None}",
        )

        # ── 9. Native stream ───────────────────────────────────────────────
        frames = api.stream(f"/api/assistants/{slug}/chat/stream", {"query": QUESTION})
        kinds: list[str] = []
        done_metadata: dict = {}
        valid = True
        for frame in frames:
            try:
                payload = json.loads(frame)
            except json.JSONDecodeError:
                valid = False
                continue
            kinds.append(payload.get("type"))
            if payload.get("type") == "done":
                done_metadata = payload.get("metadata") or {}
        check("9 every stream frame is JSON", valid and bool(frames), f"{len(frames)} frames")
        check("9 token frames streamed", "token" in kinds, f"types={sorted(set(kinds))}")
        check(
            "9 done frame carries sources",
            bool(done_metadata.get("sources")),
            f"{len(done_metadata.get('sources') or [])} sources",
        )

        # ── 10. Guardrails block ───────────────────────────────────────────
        status, blocked = api.retrieval_call(
            "POST",
            f"/api/assistants/{slug}/chat",
            {"query": f"Tell me about the {BANNED_PHRASE} material", "guardrails_config_id": guardrails_id},
        )
        blocked_text = (blocked.get("answer") or "") if isinstance(blocked, dict) else ""
        check(
            "10 guardrails block the turn",
            status == 200 and "blocked" in blocked_text.lower(),
            blocked_text[:140],
        )
        status, traces = api.retrieval_call(
            "GET", f"/guardrails/traces?config_id={guardrails_id}"
        )
        items = (traces.get("items") or []) if isinstance(traces, dict) else []
        check(
            "10 a guardrails trace is recorded",
            any(t.get("blocked") for t in items),
            f"{len(items)} traces, blocked={[t.get('blocked') for t in items][:3]}",
        )

        # ── 11. Every strategy answers ─────────────────────────────────────
        for strategy in ("vector", "lexical", "relational", "hybrid"):
            status, _ = api.ingestion_call(
                "PATCH", f"/api/pipelines/{pipeline_id}", {"rag_strategy": strategy}
            )
            if status != 200:
                check(f"11 {strategy} strategy accepted", False, f"HTTP {status}")
                continue
            status, result = api.retrieval_call(
                "POST", f"/api/assistants/{slug}/chat", {"query": QUESTION, "retrieve_limit": 10}
            )
            got = (result.get("sources") or []) if isinstance(result, dict) else []
            check(
                f"11 {strategy} returns sources",
                status == 200 and len(got) > 0,
                f"HTTP {status}, {len(got)} sources",
            )

        # ── 12. The prompt template is in force ────────────────────────────
        if short_template_id:
            status, _ = api.ingestion_call(
                "PATCH", f"/api/pipelines/{pipeline_id}", {"prompt_template_id": short_template_id}
            )
            check("12 short template attached", status == 200, f"HTTP {status}")
            status, short_answer = api.retrieval_call(
                "POST", f"/api/assistants/{slug}/chat", {"query": "What is Rohan's email?"}
            )
            words = len(((short_answer.get("answer") or "") if isinstance(short_answer, dict) else "").split())
            check("12 template governs the answer", status == 200 and words <= 12, f"{words} words")

        # ── 13. Edit the model ─────────────────────────────────────────────
        status, _ = api.ingestion_call(
            "PATCH", f"/api/pipelines/{pipeline_id}", {"chat_model": "Gpt-oss-20b"}
        )
        status, resolved = api.retrieval_call("GET", f"/api/assistants/{slug}")
        check(
            "13 chat model edited",
            status == 200 and resolved.get("chat_model") == "Gpt-oss-20b",
            f"HTTP {status}, model={resolved.get('chat_model') if isinstance(resolved, dict) else None}",
        )

    finally:
        # ── 14. Cleanup ────────────────────────────────────────────────────
        for item_id, _label in created["pipelines"]:
            api.ingestion_call("DELETE", f"/api/pipelines/{item_id}")
        for item_id, _label in created["templates"]:
            api.retrieval_call("DELETE", f"/prompt-templates/{item_id}")
        for item_id, _label in created["guardrails"]:
            api.retrieval_call("DELETE", f"/guardrails/configs/{item_id}")

        status, rows = api.ingestion_call("GET", "/api/pipelines")
        remaining = [p["name"] for p in rows] if isinstance(rows, list) else []
        leftover = [n for n in remaining if RUN_TAG in n]
        check("14 fixtures deleted", not leftover, str(remaining))

    print()
    print(f"{len(TRACE) - len(FAILURES)}/{len(TRACE)} checks passed")
    for failure in FAILURES:
        print(f"  FAILED: {failure}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
