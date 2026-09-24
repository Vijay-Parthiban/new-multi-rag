# 15 — Assistant Session Memory

**Last updated:** 2026-09-23

**Applies to:** any assistant whose Knowledge Product has the Redis destination enabled.
**Backend:** `libs/rag-core/src/rag_core/session_memory.py`, `libs/rag-core/src/rag_core/assistant.py`,
`apps/rag-api/src/rag_api/routes/chat.py`, `apps/rag-api/src/rag_api/routes/assistants.py`.
**Frontend:** the session section of the pipeline view dialog, and the `Memory` chip on a pipeline card.

## 1. What it is, and what it is not

An assistant is stateless by default: every turn is answered on its own, and a follow-up that says
"and her address?" has nothing to resolve "her" against. Session memory fixes that.

When a Knowledge Product has its Redis destination enabled, every assistant over that product gains a
**session**. A caller sends one `session_id` on every turn. The assistant remembers the exchange, replays
it on the next turn, and rewrites a follow-up into a standalone question before it searches. Ending the
session deletes everything.

It is **not**:

- A transcript store. The full history lives in Postgres (`chat_sessions` / `chat_messages`), and the
  Traces pages read that. Redis holds only what the next prompt needs.
- A semantic cache. `cache_redisvl` also stores chunk payloads for retrieval. Session keys are a separate
  namespace, so a cache purge cannot wipe a conversation and an ended session cannot drop a chunk.
- Durable. The session expires on its own TTL, and ending it is one `DEL`.
- Self-sufficient. Replaying the turns is only half of it: the system prompt must also **permit** the
  model to use them, or the grounded answer wins over the remembered one. See section 3.

## 2. The gate

The Redis destination of the Knowledge Product is the whole switch. There is no per-pipeline toggle.

| Product state | Assistant behaviour |
|---|---|
| `cache_redisvl` enabled | Session memory on. `session_memory.enabled` is `true` on `GET /api/assistants/{slug}` |
| `cache_redisvl` disabled or absent | Stateless. A `session_id` is still accepted and still groups the Postgres rows, but nothing is replayed |

Enable it on the Ingestion Manager's Knowledge Store page, under the product's destinations.

The prefix and the TTL are the destination's own, so one product's sessions can never collide with
another's, and the TTL is the value the destination already carries.

| Value | Source | Live example |
|---|---|---|
| Key prefix | `index_prefix` | `kp:tcs_store:ef2631c1` |
| TTL | `ttl_seconds`, default `86400` | 86400 (24 h) |

The full key is `{index_prefix}:memory:{session_id}`.

## 3. The turn

One turn does six things, in this order:

1. Resolve the session id. Yours if you sent one, otherwise a fresh UUID is minted and returned to you.
2. Load the remembered turns from Redis. `[]` on a new session or a Redis outage.
3. If there is history, rewrite the question into a standalone one. Retrieval, rerank and the prompt all
   use the rewritten form.
4. Retrieve and generate with the earlier turns replayed between the system message and the context
   message, so the grounding rules still apply.
5. Persist the turn in Postgres, as before.
6. Append the question and the answer to Redis and refresh the TTL.

The replay puts history **between** the system message and the context message:

```
system:    <prompt template, or the built-in RAG prompt>
user:      <earlier question>
assistant: <earlier answer>
user:      Context:
           [1] Source: <locator>
           <chunk text>

           Question: <the standalone question>
```

### The system message must allow the conversation

Replaying the turns is not enough on its own. Until **2026-09-23** the built-in RAG system prompt said
*"Answer the user's question using ONLY the numbered context passages provided in the user message"*,
and *"If no context passages … contain information relevant to the question, respond clearly that you
could not find relevant sources."*

That rule beat the conversation. The model could see the earlier turns, but the same system message
forbade using them as a source, so a question **about the conversation** — "what did I just ask?" —
was answered as a search over the documents, and refused. The retrieval was right, the memory was
right, and the answer was still wrong.

`build_rag_prompt` now appends a clause to the system message **when and only when history is
present**: the messages before the final user message are earlier turns, they may be used to understand
the question and to answer anything asked about the conversation, and the passages remain the only
source for facts about the documents. A stateless turn gets the system message byte for byte as before.

| Ask | Before | After |
|---|---|---|
| "What did I just ask you?" | *"I couldn't find any of the provided passages…"* | *"You just asked "What is the Code of Conduct?"."* |
| "And what did you answer?" | refused | *"In our previous response I explained that…"* |

Verified on a live session in both trace modes: two turns, then the follow-up recalls the first
question, and a third turn recalls the first answer.

---

## 4. Endpoints

All three require the global API key (`X-API-Key` header, or `api_key` query parameter).

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/assistants/{slug}/chat` | One turn. Add `session_id` to continue a session |
| `POST` | `/api/assistants/{slug}/chat/stream` | The same, streamed |
| `POST` | `/v1/assistants/{slug}/chat/completions` | OpenAI shape. Add the `session_id` extension field |
| `GET` | `/api/assistants/{slug}/sessions/{session_id}` | Read what the assistant remembers |
| `DELETE` | `/api/assistants/{slug}/sessions/{session_id}` | **End the session.** Clears the memory |

### 4.1 `session_id` is a UUID

Everywhere. It is the same value as the Postgres `chat_sessions` row, so Redis memory and the stored
transcript can never drift apart. Generate it once per conversation, then send it on every turn:

```
Python      str(uuid.uuid4())
JavaScript  crypto.randomUUID()
C#          Guid.NewGuid().ToString()
Go          uuid.NewString()
```

A malformed `session_id` on the OpenAI route answers `422 INVALID_SESSION_ID`. A malformed one in the URL
of the session endpoints answers `422` from the router.

### 4.2 A turn

```bash
SESSION=$(python -c "import uuid; print(uuid.uuid4())")

curl -s -X POST http://localhost:8001/api/assistants/tcs-chat/chat \
  -H "Content-Type: application/json" -H "X-API-Key: sk-bot" \
  -d "{\"query\": \"What is this document about?\", \"session_id\": \"$SESSION\"}"
```

The answer carries the session and whether the question was rewritten:

```json
{
  "message_id": "e6d1c0f4-...",
  "session_id": "7b1f0d2a-...",
  "answer": "The document covers ...",
  "sources": [{"source_locator": "tcs-handbook.pdf", "chunk_index": 3, "rerank_score": 0.91}],
  "metrics_status": "pending",
  "effective_query": null
}
```

Now the follow-up, on the **same** session:

```bash
curl -s -X POST http://localhost:8001/api/assistants/tcs-chat/chat \
  -H "Content-Type: application/json" -H "X-API-Key: sk-bot" \
  -d "{\"query\": \"Tell me more about that.\", \"session_id\": \"$SESSION\"}"
```

`effective_query` now reads `"What is the TCS onboarding handbook about?"` or similar. That is what
retrieval actually searched for. It is `null` on a first turn, because there was nothing to resolve.

### 4.3 Read a session

```bash
curl -s http://localhost:8001/api/assistants/tcs-chat/sessions/$SESSION -H "X-API-Key: sk-bot"
```

```json
{
  "session_id": "7b1f0d2a-...",
  "exists": true,
  "turns": 4,
  "ttl_seconds": 86371,
  "history": [
    {"role": "user", "content": "What is this document about?"},
    {"role": "assistant", "content": "The document covers ..."}
  ]
}
```

`exists` is `false` and `turns` is `0` for a session that never existed or has already expired. This call
never fails on an unknown session.

### 4.4 End a session

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE \
  http://localhost:8001/api/assistants/tcs-chat/sessions/$SESSION -H "X-API-Key: sk-bot"
```

`204`, always. **End it twice, or end one that already expired, and it is still 204**, so a client can
retry a failed end without checking first. That is the only idempotent guarantee in the feature, and it is
deliberate: "the user pressed End conversation" must never surface an error.

`503 SESSION_MEMORY_UNAVAILABLE` means Redis refused the delete. That is the one case a caller must
handle, because the memory is then still there.

### 4.5 Errors

| Code | HTTP | Cause |
|---|---|---|
| `SESSION_MEMORY_UNAVAILABLE` | `422` | The product has no enabled Redis destination, so the assistant has no sessions |
| `SESSION_MEMORY_UNAVAILABLE` | `503` | Redis refused the delete |
| `INVALID_SESSION_ID` | `422` | The OpenAI body carried a `session_id` that is not a UUID |

## 5. Using it from another project

### Python, OpenAI SDK

```python
import uuid
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8001/v1/assistants/tcs-chat", api_key="unused")
session_id = str(uuid.uuid4())

def ask(question: str) -> str:
    reply = client.chat.completions.create(
        model="assistant",
        messages=[{"role": "user", "content": question}],
        extra_body={"session_id": session_id},
    )
    return reply.choices[0].message.content

try:
    ask("What is this document about?")
    ask("Tell me more about that.")
finally:
    # End conversation
    import httpx
    httpx.delete(
        f"http://localhost:8001/api/assistants/tcs-chat/sessions/{session_id}",
        headers={"X-API-Key": "sk-bot"},
    )
```

The `session_id` field is not part of the OpenAI shape. Send it through `extra_body`, not as a named
argument. The non-streaming reply also carries it back under `session_id`, so a client that sent nothing
can adopt the minted one.

### JavaScript

```js
const sessionId = crypto.randomUUID();
const url = "http://localhost:8001/v1/assistants/tcs-chat/chat/completions";

async function ask(question) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: "assistant",
      messages: [{ role: "user", content: question }],
      session_id: sessionId,
    }),
  });
  return (await res.json()).choices[0].message.content;
}

async function endConversation() {
  await fetch(`http://localhost:8001/api/assistants/tcs-chat/sessions/${sessionId}`, {
    method: "DELETE",
    headers: { "X-API-Key": "sk-bot" },
  });
}
```

## 6. Limits

| Limit | Value | Where |
|---|---|---|
| Remembered messages per session | 20 (the last 10 exchanges) | `DEFAULT_MAX_TURNS` in `session_memory.py` |
| Idle expiry | The destination's `ttl_seconds`, default 86400 s | The Redis destination config |
| Rewrite output cap | 120 tokens | `_REWRITE_MAX_TOKENS` in `generator.py` |
| Rewrite growth guard | 4 × the question + 80 characters | `_REWRITE_GROWTH_FACTOR` in `generator.py` |

The trim always keeps the **newest** entries, so the oldest exchange falls out silently. A session is
never truncated mid-exchange: both messages of an exchange are appended in one Redis pipeline.

## 7. What is not remembered

- **A guardrail-blocked turn.** The question never reached the model, so storing the canned block would
  put words in the conversation that nobody said.
- **Retrieved sources.** The transcript in Postgres keeps them for the Traces pages. The prompt only needs
  the text.
- **Anything beyond the trim.** Once an exchange falls off the end of the list it is gone from the prompt.

## 8. Failure behaviour

The memory fails soft, on purpose. Losing context is better than losing the answer.

| Failure | Behaviour |
|---|---|
| Redis is down on a read | The turn runs with no history, as if stateless |
| Redis is down on a write | The answer is still returned; the exchange is not remembered |
| Redis is down on a delete | `503`. The only operation that reports failure, because the caller asked to clear data |
| Redis holds a corrupt entry | That entry is skipped; the rest of the session loads |
| The rewrite call fails | The original question is used |
| The rewrite runs away | Discarded if it exceeds the growth guard; the original question is used |

## 9. Relationship to traces

Session memory does **not** write traces. The `guardrails_traces` and `chat_pipeline_traces` rows are
unchanged, and `session_id` was already stamped on both. `effective_query` is the one new piece of
information a turn produces, and it is returned to the caller rather than stored. Whether it should land
in a trace is part of the tracing discussion that follows this feature.

## 10. Verification

- `tests/unit/test_session_memory.py` — 14 tests against a live Redis. The trim bound, the TTL refresh,
  the corrupt-entry skip, the fail-soft read and write, and the raising delete.
- `tests/unit/test_prompt_builder.py` — history placement, and the untouched two-message shape when there
  is no history.
- `scripts/e2e_session_memory.py` — the live check: it creates a pipeline, runs a session, proves the
  follow-up was rewritten, proves a second session is isolated, exercises the stream and OpenAI paths,
  ends the session and confirms the Redis key is gone.
