"""End-to-end check of the two chat conditions, in either trace mode.

    python scripts/e2e_chat_session_traces.py test
    python scripts/e2e_chat_session_traces.py prod

Runs against the live stack. It discovers one pipeline with session memory and one without,
then for each:

1. sends a question and a follow-up that only a remembered conversation can answer
2. checks the conversation was remembered, or was not
3. closes the session and reads back what the API reported
4. checks the Redis key was created during the conversation and removed by the close

The mode decides three things, and nothing else: whether the trace-mode header is sent, which
close route is used, and which tags are expected. A turn with no header is production, so the
production run is also the check that a caller needs to know nothing about the header.

The exit code is the number of failed checks, so this doubles as a gate.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
import uuid

INGESTION = "http://localhost:8007"
RAG = "http://localhost:8001"

MODE = (sys.argv[1] if len(sys.argv) > 1 else "test").strip().lower()
if MODE not in ("test", "prod"):
    print(f"mode must be test or prod, not {MODE!r}")
    raise SystemExit(1)

# None means no header at all, which is how production is expressed.
HEADER = "test" if MODE == "test" else None
TAG_SESSION = f"{MODE}-session"
TAG_STATELESS = f"{MODE}-stateless"

FAILURES = 0


def check(label: str, ok: bool, detail: str = "") -> bool:
    global FAILURES
    mark = "PASS" if ok else "FAIL"
    if not ok:
        FAILURES += 1
    print(f"  [{mark}] {label}" + (f"  -- {detail}" if detail else ""))
    return ok


def call(
    base: str,
    path: str,
    payload: dict | None = None,
    method: str | None = None,
    trace_mode: str | None = None,
    timeout: int = 300,
):
    """Return (status, body). A non-2xx is returned, not raised, so a test can assert on it."""
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        base + path, data=data, method=method or ("POST" if data else "GET")
    )
    request.add_header("Accept", "application/json")
    if data:
        request.add_header("Content-Type", "application/json")
    if trace_mode:
        request.add_header("X-RAG-Trace-Mode", trace_mode)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode()
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, raw[:400]
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def memory_gate(pipeline: dict) -> tuple[bool, str | None]:
    """Whether a pipeline keeps the conversation, and its Redis prefix.

    The same rule the backend applies: an enabled Redis destination that carries a prefix.
    """
    product = pipeline.get("knowledge_product") or {}
    for destination in product.get("destinations") or []:
        if destination.get("destination_type") != "cache_redisvl" or not destination.get("enabled"):
            continue
        prefix = (destination.get("config") or {}).get("index_prefix")
        if prefix:
            return True, str(prefix)
    return False, None


def redis_keys(prefix: str, session_id: str) -> list[str]:
    import redis

    client = redis.Redis.from_url("redis://localhost:6379/0", decode_responses=True)
    return list(client.scan_iter(match=f"{prefix}:memory:{session_id}", count=1000))


def turn(slug: str, question: str, session_id: str) -> tuple[str, str | None]:
    """One turn through the assistant route, which is the route a project calls."""
    status, body = call(
        RAG,
        f"/api/assistants/{slug}/chat",
        {"query": question, "session_id": session_id},
        trace_mode=HEADER,
    )
    if status != 200 or not isinstance(body, dict):
        return "", f"HTTP {status}: {str(body)[:200]}"
    return body.get("answer") or "", None


def close(slug: str, pipeline: dict, session_id: str):
    """End the conversation, by the route that belongs to the mode.

    A test conversation is closed on the native chat route, which is not addressed by a
    pipeline and so takes the pipeline id in the body. A production conversation is closed on
    the pipeline endpoint itself, so the caller names one thing.
    """
    if MODE == "test":
        return call(
            RAG,
            f"/chat/sessions/{session_id}/close",
            {"pipeline_id": pipeline.get("id")},
            trace_mode="test",
        )
    return call(RAG, f"/api/assistants/{slug}/sessions/{session_id}/close", method="POST")


def run(slug: str, pipeline: dict, keeps_memory: bool, prefix: str | None) -> None:
    print(f"\n=== [{MODE}] {pipeline.get('name')} ({slug}) -- memory {'ON' if keeps_memory else 'OFF'} ===")

    session_id = str(uuid.uuid4())
    if prefix:
        check("no memory key before the first turn", redis_keys(prefix, session_id) == [])

    answer, error = turn(slug, "In one sentence, what does the indexed document cover?", session_id)
    if error:
        check("first turn answered", False, error)
        return
    check("first turn answered", bool(answer), answer[:80])

    # The follow-up names nothing. Only a pipeline that kept the conversation can resolve it.
    follow_up, error = turn(slug, "And what does it say about the previous period?", session_id)
    if error:
        check("follow-up answered", False, error)
        return
    check("follow-up answered", bool(follow_up), follow_up[:80])

    if prefix:
        keys = redis_keys(prefix, session_id)
        check("session memory was written during the conversation", len(keys) == 1, f"keys={keys}")

    status, closed = close(slug, pipeline, session_id)
    if not check("close answered 200", status == 200 and isinstance(closed, dict), str(closed)[:200]):
        return

    check("close reported the turns it found", closed.get("turns") == 2, f"turns={closed.get('turns')}")
    check(
        "memory state matches the pipeline",
        closed["memory"]["enabled"] is keeps_memory,
        f"enabled={closed['memory']['enabled']}",
    )

    if keeps_memory:
        check("the session key was cleared", closed["memory"]["cleared"] is True)
        check("no session key survives the close", redis_keys(prefix or "", session_id) == [])
        check("a whole-session trace was emitted", closed["trace"]["emitted"] is True)
        check("the session trace carries a real trace id", bool(closed["trace"]["trace_id"]), str(closed["trace"]["trace_id"]))
        check(f"the tag is {TAG_SESSION}", closed["trace"]["tags"] == [TAG_SESSION], str(closed["trace"]["tags"]))
    else:
        check("a stateless pipeline exports no session trace", closed["trace"]["emitted"] is False)
        check(f"the tag is {TAG_STATELESS}", closed["trace"]["tags"] == [TAG_STATELESS], str(closed["trace"]["tags"]))

    status, _ = close(slug, pipeline, session_id)
    check("closing an already closed session is safe", status == 200, f"HTTP {status}")

    status, body = call(RAG, f"/chat/sessions/{session_id}/messages")
    items = (body or {}).get("items", []) if isinstance(body, dict) else []
    check("the closed conversation stays in chat history", status == 200 and len(items) == 4, f"messages={len(items)}")

    # A closed conversation must not block the next one.
    answer, error = turn(slug, "One more question after the session ended?", str(uuid.uuid4()))
    check(
        "a new session can follow the closed one",
        error is None and bool(answer),
        error or answer[:60],
    )


def main() -> int:
    status, pipelines = call(INGESTION, "/api/pipelines")
    if status != 200 or not isinstance(pipelines, list):
        print(f"could not list pipelines: HTTP {status} {str(pipelines)[:200]}")
        return 1

    assistants = [(p, memory_gate(p)) for p in pipelines if p.get("slug") and p.get("is_assistant")]
    keeps = next(((p, gate) for p, gate in assistants if gate[0]), None)
    stateless = next(((p, gate) for p, gate in assistants if not gate[0]), None)

    if not keeps or not stateless:
        print("need one memory-enabled pipeline and one stateless pipeline; found:")
        for pipeline, gate in assistants:
            print(f"  {pipeline.get('slug')}: memory={gate[0]}")
        return 1

    print(f"trace mode: {MODE}" + (" (header sent)" if HEADER else " (no header, which is production)"))
    run(keeps[0]["slug"], keeps[0], True, keeps[1][1])
    run(stateless[0]["slug"], stateless[0], False, None)

    print()
    print(f"{FAILURES} check(s) failed" if FAILURES else "all checks passed")
    return FAILURES


if __name__ == "__main__":
    sys.exit(main())
