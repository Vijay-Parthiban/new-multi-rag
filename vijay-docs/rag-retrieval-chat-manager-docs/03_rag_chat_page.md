# 03 — Interactive RAG Chat & Synthesis Page

**Last updated:** 2026-10-10

## 1. Executive Summary & Page Purpose

The **Chat page** (`frontend/src/pages/ChatPage.tsx`, route `/chat`) is the conversational playground for a RAG
pipeline. It selects a pipeline record, a guardrails config and per-query retrieval overrides, streams the
answer over Server-Sent Events, renders cited sources, and then polls per-message RAGAS metrics.

- Transport: the retrieval API at `RAG_API_URL = VITE_RAG_API_URL ?? "http://127.0.0.1:8001"`
  (`frontend/src/api.ts:7`). Every request sends `X-API-Key` when `VITE_RAG_API_KEY` (falling back to
  `VITE_API_KEY`) is set (`api.ts:8-9,13-15`). All routes in that app sit behind `Depends(verify_api_key)`
  (`rag-retrieval-chat-manager/backend/apps/rag-api/src/rag_api/main.py:64`), which is a no-op while `API_KEY`
  is empty (`shared-libs/platform-common/src/platform_common/auth.py`).
- The page has **two request paths**. A pipeline with a `slug` is an assistant, and the page streams from
  `/api/assistants/{slug}/chat/stream`. A pipeline with a null slug is a legacy ingestion pipeline, and the
  page streams from `/chat/stream` (§3).
- There is **no image attachment control** in the chat UI: the composer is a single text input plus `Send`.
  Multimodal content travels with the retrieval results (§9.4).
- There is **no "Guardrails: On" toggle**. The main config bar exposes a Guardrails `<select>` whose default
  option is `None`, plus every saved config (inactive ones are suffixed `(inactive)`).
- Chat users pick a pipeline by record from the selector. Each option reads `{name} ({rag_strategy})`.

---

## 2. UI Layout & Visual Components

```
+----------------------------------------------------------------------------------------------------------+
| Conversations            |  [◀ History]  Strategy: hybrid (locked)  Model: Gpt-oss-120b (locked)         |
| [+ New]                  |  session: <id prefix> or "New Session"  [End Session]  [Show settings] [Reset]|
| ------------------------ |------------------------------------------------------------------------------|
| Pipeline  [select]       |  [Retrieval mode: Hybrid][Retrieval count: 20][Rerank: on][Rerank count: 5]   |
|  Strategy: hybrid        |  [Prompt template: Pipeline default][Guardrails: None]                        |
|  Knowledge Product: name |                                                                               |
|   · <chunk_strategy>     |  You                                                            14:22         |
|  Model: Gpt-oss-120b     |  Find senior AI engineers with PyTorch, Neo4j and Qdrant experience.          |
|  Endpoint: resume-scr... |                                                                               |
|  Memory: available · 24h |  Assistant  [Normal RAG]                                         14:22        |
| ------------------------ |  Based on the indexed resumes, **Alex Chen** is a Senior AI Engineer...       |
| Chat History             |                                                                               |
|  <preview>               |  Faithful: 92%  Relevance: 88%  Ctx Prec: 75%  2 sources                      |
|  12 messages · 14:22  ⋯  |  resume_alex_chen.pdf (Score: 0.94)                                           |
|                          |  resume_elena_rostova.pdf (Score: 0.81)                                       |
|                          |  -------------------------------------------------------------------------    |
|                          |  [ Type your message...                                        ] [ Send ]     |
+----------------------------------------------------------------------------------------------------------+
|  Evaluation & Metrics (collapsible): Golden Dataset Eval | Eval Progress | Historical Metrics            |
+----------------------------------------------------------------------------------------------------------+
```

- Sidebar header `Conversations` + `+ New` button; `+ New` only clears the local session and message state.
  The server creates the session on the next message.
- Session rows show `preview` (the first user message truncated to 120 chars in the repository) or
  `Session <first 8 chars>`, the message count, and the last message time (HH:MM). A kebab menu offers
  **Delete conversation** (`ChatPage.tsx`, `rag_db/repositories/chat_repository.py`).
- Messages are sorted by `created_at` with a user-before-assistant tie-break for identical timestamps
  (`ChatPage.tsx`).
- Assistant messages render through `MarkdownMessage` (`react-markdown` + `remark-gfm` + `remark-math` +
  `rehype-katex`, `frontend/src/components/MarkdownMessage.tsx`). User text is rendered verbatim.
- Source citations show **only the first 3** reranked chunks as
  `📄 <source_locator> (Score: <rerank_score to 2dp>)` plus an `N sources` badge (`ChatPage.tsx:1306`).
  There is no chunk inspector drawer and no chunk-index display.
- While streaming, the pending assistant bubble shows the current `status` message with a pulsing dot, then
  the streamed markdown with a blinking cursor.
- Collapsible **Evaluation & Metrics** panel: golden-dataset picker + `Run Pipeline Eval`, live eval-run
  progress (status, `items_completed/items_total`, numeric aggregate metrics from the
  `retrieval`/`reranker`/`generation` blocks with a leading `mean_` stripped), and historical averages
  computed client-side from `GET /chat/stats?limit=10`.

### 2.1 The pipeline information block

The sidebar block under the pipeline selector shows five lines:

| Line | Value |
|---|---|
| `Strategy:` | `selectedPipeline.rag_strategy` |
| `Knowledge Product:` | The product's `name`, then ` · ` and its `chunk_strategy` |
| `Model:` | `selectedPipeline.chat_model` |
| `Endpoint:` | `selectedPipeline.slug` |
| `Memory:` | `available · 24h TTL`, or `not available` |

The `Knowledge Product:`, `Model:` and `Endpoint:` lines render only when the record carries the value. The
whole block renders only when a pipeline is selected.

The `Memory:` line is the one that decides how the page behaves. It is computed by
`sessionMemoryFor(selectedPipeline.knowledge_product.destinations)` — the same rule the backend applies and
the Pipelines page shows: an **enabled** `cache_redisvl` destination that carries an `index_prefix`. A green
chip reads `available · {n}h TTL`; an amber chip reads `not available`. Nothing about the pipeline is
different; the Knowledge Product is what decides.

**The embedding model and the sparse model lines are gone.** They were misleading: an assistant resolves its
collection, embedding model and strategy from its Knowledge Product, and a legacy pipeline's models never
travel on the wire from this page any more. The `Endpoint:` line shows the raw slug, not a full URL. The full
URL is on the Pipelines page (doc 02 §8).

---

## 3. The Request Path

`handleSendMessage` builds one payload, then chooses the path (`ChatPage.tsx`).

### 3.1 An assistant (the record has a slug)

```ts
const assistantSlug = selectedPipeline?.slug ?? null;
for await (const event of streamChat(
    payload,
    assistantSlug ? { path: `/api/assistants/${assistantSlug}/chat/stream` } : {},
)) { … }
```

The page sends the query, the session id, the selected pipeline's id, and the per-turn overrides: the
guardrails config, the prompt template and the model settings (`ChatPage.tsx:521-538`). It does **not** send
`collection`, `embedding_model` or `sparse_embedding_model`, because the assistant resolves them from its
Knowledge Product. It also does not run the image-only dense override, because an assistant has no `modality`
field.

`streamChat` (`frontend/src/api.ts:1038`) takes an optional `opts` object: `{ path?, traceMode? }`. The default path stays `/chat/stream`.

### 3.2 A legacy ingestion pipeline (the slug is null)

The page keeps the old path: `POST /chat/stream` with no `path` override. The payload also carries the
record's own retrieval settings:

- `collection` = `selectedPipeline.qdrant_collection`
- `embedding_model` = `selectedPipeline.embedding_model`
- `sparse_embedding_model`, only when the record has one
- `retrieval_mode` forced to `"dense"` when `modality === "image"`, or when the strategy is `multimodal` and
  the record has no sparse model. Image-only indexes have no sparse vectors.

The `Router`, `Classifier`, `RAG Mode` and `Max Loops` controls are gone (§4), so a legacy pipeline now runs
the plain retrieval path only.

### 3.3 The payload

| Key | Value sent by the page |
|---|---|
| `query` | The message text. |
| `session_id` | The active session, or `null` for a new chat. |
| `retrieval_mode` | The settings-panel Retrieval mode: `hybrid` \| `dense` \| `sparse`. |
| `retrieve_limit` | The settings-panel Retrieval count, seeded from the pipeline's `retrieve_limit` (20 when the record carries none). |
| `rerank_enabled` | The settings-panel Rerank checkbox, seeded from the pipeline's `rerank_enabled` (true when the record carries none). |
| `top_k` | The settings-panel Rerank count, seeded from the pipeline's `rerank_top_k` (5 when the record carries none). |
| `guardrails_config_id` | The selected guardrails config id, omitted when `None`. |
| `prompt_template_id` | The selected prompt template id, omitted when empty. An override for this turn only. |
| `model_settings` | The model-settings overrides from the form (`temperature`, `top_p`, `top_k`, `max_tokens`). |
| `pipeline_id` | The selected pipeline's id. Names the pipeline for the trace; the backend reads the records itself |
| `collection`, `embedding_model`, `sparse_embedding_model` | Legacy path only, copied from the record. |

On the assistant path the server applies `AssistantChatRequest`
(`rag-retrieval-chat-manager/backend/apps/rag-api/src/rag_api/routes/assistants.py:56-74`). A missing
`retrieval_mode` becomes `dense`, because the fanout collections hold dense vectors only. A `hybrid` request
against a product with no Qdrant collection also becomes `dense`. A request-level `guardrails_config_id` wins
over the pipeline's own config, so the page can test another config without editing the pipeline.

The request leaves every retrieval setting optional. A request that names
none takes `PipelineConfig`'s defaults: `retrieval_mode=hybrid`, `retrieve_limit=20`,
`rerank_enabled=true`, `top_k=5` (`rag_core/schemas.py:36-41`). The Chat page names `retrieve_limit`,
`rerank_enabled` and `top_k` on every turn, so those defaults apply only to a caller that sends none. The
page reads the three from the selected pipeline's own columns first, with 20, true and 5 as the fallbacks
when a record carries none. The generation model falls back to `settings.chat_model`.

The page has no reranker-model control, so it sends no `rerank_model`. Unlike the sampling settings and the
three retrieval numbers, a Chat-page turn cannot override the reranker a pipeline pins. On the assistant path
the endpoint resolves it from the pipeline record, so the pipeline's pinned model reorders the chunks, and the
deployment's model (`settings.reranker_model`, `nvidia-rerank`) applies only when the pipeline pins none. A
pipeline with no slug is a legacy ingestion pipeline: its turn goes to `POST /chat/stream`, which does not read
the pipeline record, so the deployment's model applies there.

### 3.4 Controls that remain

| Control | Where | Values |
|---|---|---|
| `Retrieval mode` | Settings row | `Hybrid`, `Dense`, `Sparse` |
| `Retrieval count` | Settings row | 1–50, seeded from the pipeline's `retrieve_limit` (20 when the record carries none). While `Rerank` is off, the hint reads that all retrieved chunks reach the prompt. |
| `Rerank` | Settings row | A checkbox, seeded from the pipeline's `rerank_enabled` (`true` when the record carries none). |
| `Rerank count` | Settings row | 1–50, seeded from the pipeline's `rerank_top_k` (5 when the record carries none). The control renders only while `Rerank` is on, so the panel hides it when reranking is off. |
| `Prompt template` | Settings row | `Pipeline default`, or one saved template. An override for this turn only. |
| `Guardrails` | Settings row | `None`, or one saved config. Inactive configs read `{name} (inactive)`. |
| Model settings | Settings row | `temperature`, `top_p`, `top_k`, `max_tokens`, seeded from the pipeline. |

The config bar also shows the session indicator: a dot, plus the first 12 characters of the session id or
`New Session`.

### 3.5 The trace mode header

Every turn the page sends carries `X-RAG-Trace-Mode: test` (`ChatPage.tsx:575`, `TRACE_MODE_HEADER` in `api.ts:1035`). The header is omitted unless `traceMode` is set, and an omitted header means production on the backend.

This matters because the page and an external caller hit **the same route**. The header is the only thing that separates them in the backends, and it is what tags the row `test` on the Real Time Monitoring page. A caller that knows nothing about the header cannot label real traffic as a test. Full detail: [16 — Observability and Tracing](./16_observability_tracing.md).

### 3.6 The conversation lifecycle

The page starts with no conversation open, and the flow is the same in both conditions.

| Step | State | What the page shows |
|---|---|---|
| Load | Nothing open | `Click New to start chatting`. The composer is disabled, and the placeholder reads `Click + New to start chatting` |
| Press **+ New** | A conversation exists | `New conversation`, a live composer, and the End button |
| Send turns | The conversation grows | Normal Q/A. With memory, a follow-up is understood in context |
| Press **End Session** / **End Chat** | A confirmation | `window.confirm`, then the conversation closes and the area returns to the first state |
| Open a row in Chat History | That conversation | Its stored messages, and a live composer |

`composerReady` is what gates the first state, and it is set by **+ New** or by opening a history row. It is
cleared again by ending the conversation. The composer stays disabled until then, so a turn is never sent
into a session nobody opened.

**The button label follows the memory state.** A pipeline with session memory gets **End Session**: there is
memory to drop and a whole conversation to export. One without gets **End Chat**: it kept nothing, so there is
nothing to clear.

Both buttons call `POST /chat/sessions/{id}/close`. The difference is entirely server-side, decided by the
same Knowledge Product gate. What each condition does:

| | Memory enabled | No memory |
|---|---|---|
| Confirmation text | `End this session? …` | `Close this chat? …` |
| Memory dropped | Yes — the Redis key is deleted | Nothing to drop |
| Session trace | One trace holding every Q/A pair | None. Each turn was already traced alone |
| Tag | `test-session` | `test-stateless` |
| History | The conversation stays, and is listed under Chat History | The same |

Closing twice is safe: the endpoint answers 200 both times. The conversation is never deleted by closing it
— only `Delete conversation` in the row menu removes it from history.

---

## 4. Controls the Page No Longer Offers

Four controls are gone from the toolbar and the payload:

| Removed control | Payload keys it sent |
|---|---|
| `Router` toggle | `router_enabled`, `router_mode` |
| `Classifier` select | `router_mode` |
| `RAG Mode` select | `rag_mode` |
| `Max Loops` input | `self_corrective_max_loops` |

**Reason:** the LLM query router and self-corrective RAG were never implemented. The old code imported
`rag_core.query_router`, a module that never existed, so `POST /chat/stream` returned 500 on every request.
The dead branch and the dead `config.rag_mode` read are gone
(`rag-retrieval-chat-manager/backend/apps/rag-api/src/rag_api/routes/chat.py`). The page stops
offering a switch with no behaviour behind it.

The server reports `route: "normal"` in the `done` metadata and in the `session` frame, and `route:
"blocked"` after a guard blocks the turn. Those two are the only values the server emits now.

Three leftovers went with the controls, so nothing in the page refers to a router or to self-corrective RAG:

- The route badge map held four unreachable labels: `greeting`, `simple_rag_auto`, `self_corrective` and
  `self_corrective_auto`. It now holds `normal` and `blocked` only.
- The RAGAS panel held a branch that rendered `sc_iterations`, a self-corrective field that nothing ever
  wrote. The branch is gone.
- The chat empty state carried a sentence about an "Intelligent (Auto)" classifier that picks greeting,
  simple RAG or CRAG per query. It now explains whether the selected pipeline keeps the conversation, and
  how to start one.

One badge remains: the page renders a `🔁 N loops` chip when `latency_ms.sc_loops > 1`
(`ChatPage.tsx:1205-1218`). Nothing in the backend writes `sc_loops`, so the chip stays hidden with the
current pipeline.

---

## 5. SSE Framing and Event Contract

Framing: `media_type="text/event-stream"`, headers `Cache-Control: no-cache` and `X-Accel-Buffering: no`.
Every frame is `data: <json>\n\n`. The generator runs in a worker thread and bridges chunks through a queue so
the OpenTelemetry context survives.

| `type` | Payload keys | Emitted when |
|---|---|---|
| `status` | `message` | `"Checking guardrails..."` before an input guardrail check (`routes/chat.py:794`). The pipeline also sends `"Retrieving context"` and `"Generating answer"` (`rag_core/pipeline.py`). |
| `token` | `content` | One frame per non-empty answer delta (`routes/chat.py`, `rag_core/pipeline.py`). |
| `done` | `metadata` | The pipeline's done metadata: `answer`, `sources`, `retrieved_chunks`, `reranked_chunks`, `latency_ms` and `route: "normal"` (`rag_core/pipeline.py`). |
| `session` | `session_id`, `message_id`, `route`, `metrics_status` | After the DB write. `route` is `blocked` on an input, retrieval or output block, otherwise `normal` (`routes/chat.py`). |
| `blocked` | `content`, `blocked_by_guard`, `blocked_on`, `blocked_title`, `session_id`, `message_id`, `route`, `metrics_status` | An input, a retrieval or an output guardrail block. `blocked_on` is `input`, `retrieval` or `output` (`routes/chat.py`). |
| `error` | `content` | Any exception in the worker, including `str(e)` (`routes/chat.py:989`). |

The client splits the byte stream on `\n\n`, keeps only lines starting with `data: `, and `JSON.parse`s each
into a `ChatStreamEvent` whose declared fields are `type`, `message`, `content`, `session_id`, `message_id`,
`route`, `metrics_status`, `blocked_by_guard`, `blocked_on`, `blocked_title` and `metadata`
(`api.ts:1010-1033`). The page prefers the `session` event's real ids over the `done` metadata, and marks a turn
`blocked` when a `blocked` event arrived (`ChatPage.tsx`).

---

## 6. Guardrail Blocking and `BlockedCard`

The chat handlers run the guardrail check on the `guardrails_config_id`, for the input, for the retrieval and
for the output.

- Blocked **input**: the stored answer becomes `GUARD_BLOCK_COPY[guard]["input"]`, and the trace stores
  `latency_ms = {route: "blocked", blocked: true, blocked_by_guard, blocked_on}`. Metrics are not enqueued.
- Blocked **retrieval**: the turn stops after the rerank and before the model reads the passages. `rag-core`
  raises `GuardrailBlocked` (`rag_core/pipeline.py:60`) through the `chunk_filter` it runs at
  `rag_core/pipeline.py:248,333`, and the route persists the turn and answers with
  `GUARD_BLOCK_COPY[guard]["retrieval"]`, `latency_ms.blocked_on = "retrieval"`, empty `sources`, and no
  memory append (`routes/chat.py:625-659`, `:864-890`). Metrics are not enqueued.
- Blocked **output**: the streamed answer is replaced, the same blocked latency keys are merged in, and
  metrics are not enqueued.
- Each phase that runs writes one `guardrails_traces` row. A phase with nothing applicable writes no row
  (`routes/chat.py:429-431`).
- `GUARD_BLOCK_COPY` covers the three validators and the six engine rails — `ban_list`, `detect_pii`,
  `toxic_language`, `self_check_input`, `jailbreak_heuristics`, `pii_retrieval`, `self_check_output`,
  `self_check_facts` (`routes/chat.py:163`). Each has an `input` and an `output` sentence, and `pii_retrieval`
  also has a `retrieval` sentence. When a guard id is absent from the map, `_blocked_answer` falls back to
  `"<Phase> blocked by guardrail: <guard or 'unknown'>."` (`routes/chat.py:210-212`). The SSE `blocked` frame
  also carries `blocked_title` (the copy map's title, else the guard name, else `"Guardrail"`).
- The guardrails service names its guard `ban-list`, while the stored config uses `ban_list`.
  `rag_shared/guardrails_client.py` maps `_` to `-`, so the check reaches the service. Before that fix every
  check returned 404, the client read a non-200 as "passed", and no guardrail ever blocked anything.

`BlockedCard` (`ChatPage.tsx:83`) maps `blocked_by_guard` to an icon, a title and a tone: `ban_list` → 🚫
`Banned keyword`, `detect_pii` → 🔒 `Personal information`, `toxic_language` → ⚠️ `Toxic language`. The five
engine rails have their own cards: `self_check_input` and `self_check_output` → 🛡️ the check title,
`jailbreak_heuristics` → 🕵️ `Jailbreak attempt`, `pii_retrieval` → 📄 `Personal information in the sources`,
`self_check_facts` → 🔗 `Answer not supported by the sources`. Any other guard falls back to 🛡️ with the guard
name as the title. The phase label is `Response blocked` when `blocked_on === "output"`, `Sources blocked`
when `blocked_on === "retrieval"`, otherwise `Input blocked`. The body is the server `content`, with a
generic hint as the fallback. The CSS classes are `chat-blocked-card` and `chat-blocked-card--<tone>`, where the
six rails use the new `--security` or the shared `--pii` tone. The server-supplied `blocked_title` is not used
by the UI. A card renders whenever `m.blocked` is true or the stored trace route is `blocked`.

---

## 7. Non-Streaming `POST /chat`

Returns `ChatResponse`: `message_id`, `session_id`, `answer`, `sources`
(`[{source_locator, chunk_index, rerank_score}]`, taken from the reranked chunks), `trace_id` and
`metrics_status`. Guardrails run the same way: an input block returns early with empty sources, a retrieval
block returns the same shape before generation, and an output block rewrites the answer.

The Chat page never calls this route. The assistant surface does: `POST /api/assistants/{slug}/chat` returns
the same shape, and `POST /v1/assistants/{slug}/chat/completions` wraps it in the OpenAI shape. Those routes
delegate to this handler, so guardrails, retrieval, rerank, generation, persistence and metrics are not
duplicated.

---

## 8. Metrics Polling

After a turn, the page polls `GET /chat/messages/{message_id}/metrics` every **2500 ms**, up to **40**
attempts, and tolerates HTTP 404 for the first **8** attempts (the worker may not have created the row yet)
(`ChatPage.tsx:394-414`). It skips polling for blocked turns and for messages whose `metrics_status` is
`skipped` or `failed` (`ChatPage.tsx:262-268`). When a poll returns `completed`, the historical stats are
refreshed.

---

## 9. Backend APIs & Contracts

All paths are relative to the retrieval API base URL. Auth is the `X-API-Key` header or the `api_key` query
parameter, and both are optional while `API_KEY` is empty.

| Method | Endpoint | Description | Request / Response |
|---|---|---|---|
| `POST` | `/api/assistants/{slug}/chat/stream` | The stream an assistant uses | `AssistantChatRequest` → `text/event-stream` |
| `POST` | `/api/assistants/{slug}/chat` | The non-streaming assistant turn | `AssistantChatRequest` → `ChatResponse` |
| `POST` | `/v1/assistants/{slug}/chat/completions` | The OpenAI shape | `{model?, messages[], stream?, temperature?, max_tokens?, user?}` |
| `POST` | `/chat` | Non-streaming RAG turn (persists both messages) | `ChatRequest` → `ChatResponse` |
| `POST` | `/chat/stream` | SSE token stream for a legacy pipeline | `ChatRequest` → `text/event-stream` |
| `GET` | `/chat/sessions?limit=50` | Sessions, newest activity first | → `{limit, count, items: [ChatSessionItem]}` |
| `GET` | `/chat/sessions/{session_id}/messages` | Ordered history with route, sources and metrics status | 404 when the session is unknown |
| `DELETE` | `/chat/sessions/{session_id}` | Deletes a conversation | → `204 No Content` |
| `DELETE` | `/chat/messages/{message_id}` | Deletes one assistant turn **and its question** | → `{session_id, deleted_message_ids}` |
| `GET` | `/chat/messages/{message_id}/metrics` | RAGAS metrics for one assistant message | → `MetricsResponse`, 404 while no row exists |
| `GET` | `/chat/stats?limit=20` | Recent assistant messages with metrics | `limit` must be 1–100 or 422 |

The assistant routes answer `404 ASSISTANT_NOT_FOUND` for an unknown slug, `422 NOT_AN_ASSISTANT` for a legacy
ingestion pipeline, `422 RAG_STRATEGY_UNAVAILABLE` when a store the strategy needs is missing, and
`503 INGESTION_SERVICE_UNAVAILABLE` when the ingestion service does not answer
(`rag-retrieval-chat-manager/backend/apps/rag-api/src/rag_api/routes/assistants.py:160-198`).

### 9.1 Sessions and message deletion

- Session **creation** is implicit: `_persist_chat_turn` reuses `session_id` when the row exists and otherwise
  creates a session. There is no `POST /chat/sessions`.
- `ChatSessionItem` keys: `session_id`, `created_at`, `last_message_at`, `preview`, `message_count`. `preview`
  is the first user message truncated to 120 chars. Because `list_sessions` inner-joins `chat_messages`, a
  session with no messages is never listed (`chat_repository.py:192-226`).
- `ChatMessageItem` keys: `id`, `role`, `content`, `created_at`, `trace` (`retrieval_mode`, `rerank_enabled`,
  `generation_model`, `route`), `sources`, `metrics_status`, `blocked`, `blocked_by_guard`, `blocked_on`.
  `route` is read from the stored trace `latency_ms.route`, and `blocked` is true when `latency_ms.blocked` is
  set or that route is `blocked` (`routes/chat.py`).
- `DELETE /chat/sessions/{id}` soft-deletes the conversation and its turns and answers 204.
  `DELETE /chat/messages/{id}` returns `deleted_message_ids` covering the reply and its question. The
  `deleted_at` columns and both repository methods came in migration `005`.
- `POST /chat/sessions/{id}/close` ends a conversation. It writes the whole-session trace and drops the
  Redis memory key, and answers with the turn count, the memory result and the trace result:

  ```json
  {
    "session_id": "…",
    "turns": 2,
    "memory": { "enabled": true, "cleared": true },
    "trace": { "emitted": true, "trace_id": "12047f48…", "tags": ["test-session"] }
  }
  ```

  It is idempotent, so a second call answers 200 again. It never deletes the conversation: the turns stay in
  history. See [16 — Observability and Tracing](./16_observability_tracing.md) §4 for what it exports.

### 9.2 Per-message metrics

`MetricsResponse`: `message_id`, `status` (`pending` | `completed` | `failed`), `faithfulness`,
`answer_relevancy`, `context_precision`, `context_recall`, `kendall_tau`, `mrr`, `ndcg`, `metrics` and
`error_message`. The three ranking scores come from `metrics.raw_ragas["reranker"]`. `metrics` is the staged
RAGAS payload, and it is `null` unless `raw_ragas` contains a `retrieval`, a `reranker` or a `generation`
block. Rows are created with status `pending` and a queued `eval_worker.tasks.compute_chat_metrics` job when
`settings.ragas_enabled` and `settings.chat_metrics_async` are both true (the defaults); otherwise
`metrics_status` is `skipped`.

### 9.3 Chat stats

`ChatStatItem` returns `message_id`, `session_id`, `query`, `answer`, `faithfulness`, `answer_relevancy`,
`context_precision`, `context_recall`, `kendall_tau`, `mrr`, `ndcg`, `metrics`, `metrics_status`,
`computed_at`, `latency_ms`, `retrieval_mode`, `rerank_enabled`, `generation_model` and `created_at`. The page
requests `limit=10` and averages `faithfulness` and `answer_relevancy` over the items that carry either value.

### 9.4 Multimodal image inputs

Images are **never uploaded from the chat UI**. They travel with the retrieval results.

1. When a query runs against a store that holds image chunks (chunk `type == "image"`, content starting with
   `data:image/`, or `image_base64` plus `mime_type` metadata), `Generator.generate` splits the reranked chunks
   into a text group and an image group (`generation_core/generator.py`, `rag_shared/chunk_utils.py`).
2. The text chunks go to the chat model with the numbered-context RAG prompt (`generator.py`,
   `prompt_builder.py`).
3. The image chunks go to the vision model, named by the request `vision_model` or `settings.vision_model`,
   default **`groq-vision`**, as an OpenAI multimodal message: one instruction text part, then per image a
   `[Image N] Source: <locator>` caption part and a `{"type": "image_url", "image_url": {"url": <data URI>}}`
   part. At most **3** images are attached, with `max_tokens=1024` and `temperature=0.2`
   (`generation_core/vision_generator.py`).
4. When both a text answer and a vision answer exist, a third call to the `fusion_model` merges them.
   Otherwise the single available answer is returned. With no relevant chunks the answer is
   `NO_SOURCES_ANSWER`: `"I could not find any relevant sources in the knowledge base to answer this
   question."` (`prompt_builder.py`).
5. **A vision answer cannot stream.** With image chunks present, `generate_stream` makes one blocking call and
   yields the whole answer as a single `token` event. A text-only turn streams normally.
6. `vision_model` and `fusion_model` are accepted overrides on `ChatRequest`, but the chat UI never sets them.
   Only an API client can pass `generation_model`, `vision_model` or `fusion_model`.

---

## 10. Notes and Limits

- **The assistant route is single-turn for the OpenAI shape only.** `POST /v1/assistants/{slug}/chat/completions`
  takes the last `role=user` message as the question and ignores earlier turns. The native route
  (`/api/assistants/{slug}/chat/stream`) keeps sessions through `session_id`.
- **A legacy pipeline stays usable from this page.** The Chat page keeps `/chat/stream` and the record's own
  collection and models for a pipeline with a null slug.
- **`Settings.chat_model` is still `llama-3.3-70b-versatile`,** which the proxy does not serve. An assistant
  always carries an explicit `chat_model`, so this page cannot reach that default on the assistant path.
