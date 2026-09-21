# 03 — Interactive RAG Chat & Synthesis Page

**Last updated:** 2026-09-21

## 1. Executive Summary & Page Purpose

The **Chat page** (`frontend/src/pages/ChatPage.tsx`, route `/chat`) is the conversational playground for a RAG
pipeline. It selects a pipeline record, a guardrails config and per-query retrieval overrides, streams the
answer over Server-Sent Events, renders cited sources, and then polls per-message RAGAS metrics.

- Transport: the retrieval API at `RAG_API_URL = VITE_RAG_API_URL ?? "http://localhost:8001"`
  (`frontend/src/api.ts:5`). Every request sends `X-API-Key` when `VITE_RAG_API_KEY` (falling back to
  `VITE_API_KEY`) is set (`api.ts:6-7,16-18`). All routes in that app sit behind `Depends(verify_api_key)`
  (`rag-retrieval-chat-manager/backend/apps/rag-api/src/rag_api/main.py:64`), which is a no-op while `API_KEY`
  is empty (`shared-libs/platform-common/src/platform_common/auth.py:16-39`).
- The page has **two request paths**. A pipeline with a `slug` is an assistant, and the page streams from
  `/api/assistants/{slug}/chat/stream`. A pipeline with a null slug is a legacy ingestion pipeline, and the
  page streams from `/chat/stream` (§3).
- There is **no image attachment control** in the chat UI: the composer is a single text input plus `Send`.
  Multimodal content travels with the retrieval results (§9.4).
- There is **no "Guardrails: On" toggle**. The sidebar exposes a Guardrails `<select>` whose default option is
  `None`, plus every saved config (inactive ones are suffixed `(inactive)`).
- Chat users pick a pipeline by record from the selector. Each option reads `{name} ({rag_strategy})`.

---

## 2. UI Layout & Visual Components

```
+----------------------------------------------------------------------------------------------------------+
| Conversations            |  [Mode: Hybrid][Limit: 20][Rerank: on][Top K: 5]                              |
| [+ New]                  |  session: <id prefix> or "New Session"                                        |
| ------------------------ |  You                                                            14:22         |
| Pipeline  [select]       |  Find senior AI engineers with PyTorch, Neo4j and Qdrant experience.          |
|  Strategy: hybrid        |                                                                               |
|  Knowledge Product: name |  Assistant  [Normal RAG]                                         14:22        |
|   · <chunk_strategy>     |  Based on the indexed resumes, **Alex Chen** is a Senior AI Engineer...       |
|  Model: Gpt-oss-120b     |                                                                               |
|  Endpoint: resume-scr... |  Faithful: 92%  Relevance: 88%  Ctx Prec: 75%  2 sources                      |
| ------------------------ |  resume_alex_chen.pdf (Score: 0.94)                                           |
| Guardrails [select: None]|  resume_elena_rostova.pdf (Score: 0.81)                                       |
|  Mode: input             |  -------------------------------------------------------------------------    |
|  Guards: ban_list, ...   |  [ Type your message...                                        ] [ Send ]     |
| ------------------------ |                                                                               |
| Chat History             |                                                                               |
|  <preview>               |                                                                               |
|  12 messages · 14:22  ⋯  |                                                                               |
+----------------------------------------------------------------------------------------------------------+
|  Evaluation & Metrics (collapsible): Golden Dataset Eval | Eval Progress | Historical Metrics            |
+----------------------------------------------------------------------------------------------------------+
```

- Sidebar header `Conversations` + `+ New` button; `+ New` only clears the local session and message state.
  The server creates the session on the next message.
- Session rows show `preview` (the first user message truncated to 120 chars in the repository) or
  `Session <first 8 chars>`, the message count, and the last message time (HH:MM). A kebab menu offers
  **Delete conversation** (`ChatPage.tsx:654-690`, `rag_db/repositories/chat_repository.py:150`).
- Messages are sorted by `created_at` with a user-before-assistant tie-break for identical timestamps
  (`ChatPage.tsx:530-542`).
- Assistant messages render through `MarkdownMessage` (`react-markdown` + `remark-gfm` + `remark-math` +
  `rehype-katex`, `frontend/src/components/MarkdownMessage.tsx:1-5`). User text is rendered verbatim.
- Source citations show **only the first 3** reranked chunks as
  `📄 <source_locator> (Score: <rerank_score to 2dp>)` plus an `N sources` badge (`ChatPage.tsx:921-935`).
  There is no chunk inspector drawer and no chunk-index display.
- While streaming, the pending assistant bubble shows the current `status` message with a pulsing dot, then
  the streamed markdown with a blinking cursor.
- Collapsible **Evaluation & Metrics** panel: golden-dataset picker + `Run Pipeline Eval`, live eval-run
  progress (status, `items_completed/items_total`, numeric aggregate metrics from the
  `retrieval`/`reranker`/`generation` blocks with a leading `mean_` stripped), and historical averages
  computed client-side from `GET /chat/stats?limit=10`.

### 2.1 The pipeline information block

The sidebar block under the pipeline selector shows four lines:

| Line | Value |
|---|---|
| `Strategy:` | `selectedPipeline.rag_strategy` |
| `Knowledge Product:` | The product's `name`, then ` · ` and its `chunk_strategy` |
| `Model:` | `selectedPipeline.chat_model` |
| `Endpoint:` | `selectedPipeline.slug` |

The `Knowledge Product:`, `Model:` and `Endpoint:` lines render only when the record carries the value. The
whole block renders only when a pipeline is selected.

**The embedding model and the sparse model lines are gone.** They were misleading: an assistant resolves its
collection, embedding model and strategy from its Knowledge Product, and a legacy pipeline's models never
travel on the wire from this page any more. The `Endpoint:` line shows the raw slug, not a full URL. The full
URL is on the Pipelines page (doc 02 §8).

---

## 3. The Request Path

`handleSendMessage` builds one payload, then chooses the path (`ChatPage.tsx:371-406`).

### 3.1 An assistant (the record has a slug)

```ts
const assistantSlug = selectedPipeline?.slug ?? null;
for await (const event of streamChat(
    payload,
    assistantSlug ? { path: `/api/assistants/${assistantSlug}/chat/stream` } : {},
)) { … }
```

The page sends only `query`, `session_id` and the toolbar overrides. It does **not** send `collection`,
`embedding_model` or `sparse_embedding_model`, because the assistant resolves them from its Knowledge Product.
It also does not run the image-only dense override, because an assistant has no `modality` field.

`streamChat` (`frontend/src/api.ts:900`) takes an optional `{ path }` argument. The default path stays
`/chat/stream`.

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
| `retrieval_mode` | The toolbar Mode: `hybrid` \| `dense` \| `sparse`. |
| `retrieve_limit` | The toolbar Limit (1–50, default 20). |
| `rerank_enabled` | The toolbar Rerank checkbox (default on). |
| `top_k` | The toolbar Top K (1–20, default 5). |
| `guardrails_config_id` | The selected guardrails config id, omitted when `None`. |
| `collection`, `embedding_model`, `sparse_embedding_model` | Legacy path only, copied from the record. |

On the assistant path the server applies `AssistantChatRequest`
(`rag-retrieval-chat-manager/backend/apps/rag-api/src/rag_api/routes/assistants.py:51-63`). A missing
`retrieval_mode` becomes `dense`, because the fanout collections hold dense vectors only. A `hybrid` request
against a product with no Qdrant collection also becomes `dense`. A request-level `guardrails_config_id` wins
over the pipeline's own config, so the page can test another config without editing the pipeline.

Server-side defaults come from `PipelineConfig`: `retrieval_mode=hybrid`, `retrieve_limit=20`,
`rerank_enabled=true`, `top_k=5` (`rag_core/schemas.py:9-13`). The generation model falls back to
`settings.chat_model`.

### 3.4 Controls that remain

| Control | Where | Values |
|---|---|---|
| `Mode` | Toolbar | `Hybrid`, `Dense`, `Sparse` |
| `Limit` | Toolbar | 1–50, default 20 |
| `Rerank` | Toolbar | A checkbox, default on |
| `Top K` | Toolbar | 1–20, default 5. The group renders only while `Rerank` is on. |
| Guardrails config | Sidebar | `None`, or one saved config. Inactive configs read `{name} (inactive)`. |

The toolbar also shows the session indicator: a dot, plus the first 12 characters of the session id or
`New Session`.

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
(`rag-retrieval-chat-manager/backend/apps/rag-api/src/rag_api/routes/chat.py:570-580`). The page stops
offering a switch with no behaviour behind it.

The server reports `route: "normal"` in the `done` metadata and in the `session` frame, and `route:
"blocked"` after a guard blocks the turn. Those two are the only values the server emits now.

Three leftovers went with the controls, so nothing in the page refers to a router or to self-corrective RAG:

- The route badge map held four unreachable labels: `greeting`, `simple_rag_auto`, `self_corrective` and
  `self_corrective_auto`. It now holds `normal` and `blocked` only.
- The RAGAS panel held a branch that rendered `sc_iterations`, a self-corrective field that nothing ever
  wrote. The branch is gone.
- The chat empty state carried a sentence about an "Intelligent (Auto)" classifier that picks greeting,
  simple RAG or CRAG per query. It now describes the two real request paths.

---

## 5. SSE Framing and Event Contract

Framing: `media_type="text/event-stream"`, headers `Cache-Control: no-cache` and `X-Accel-Buffering: no`.
Every frame is `data: <json>\n\n`. The generator runs in a worker thread and bridges chunks through a queue so
the OpenTelemetry context survives.

| `type` | Payload keys | Emitted when |
|---|---|---|
| `status` | `message` | `"Checking guardrails..."` before an input guardrail check (`routes/chat.py:529`). The pipeline also sends `"Retrieving context"` and `"Generating answer"` (`rag_core/pipeline.py:160,176`). |
| `token` | `content` | One frame per non-empty answer delta (`routes/chat.py:589-596`, `rag_core/pipeline.py:187`). |
| `done` | `metadata` | The pipeline's done metadata: `answer`, `sources`, `retrieved_chunks`, `reranked_chunks`, `latency_ms` and `route: "normal"` (`rag_core/pipeline.py:193-210`). |
| `session` | `session_id`, `message_id`, `route`, `metrics_status` | After the DB write. `route` is `blocked` on an output block, otherwise `normal` (`routes/chat.py:657-659`). |
| `blocked` | `content`, `blocked_by_guard`, `blocked_on`, `blocked_title`, `session_id`, `message_id`, `route`, `metrics_status` | An input or an output guardrail block (`routes/chat.py:143-170,556,656`). |
| `error` | `content` | Any exception in the worker, including `str(e)` (`routes/chat.py:661-662`). |

The client splits the byte stream on `\n\n`, keeps only lines starting with `data: `, and `JSON.parse`s each
into a `ChatStreamEvent` whose declared fields are `type`, `message`, `content`, `session_id`, `message_id`,
`route`, `metrics_status`, `blocked_by_guard`, `blocked_on`, `blocked_title` and `metadata`
(`api.ts:880-928`). The page prefers the `session` event's real ids over the `done` metadata, and marks a turn
`blocked` when a `blocked` event arrived (`ChatPage.tsx:410-467`).

---

## 6. Guardrail Blocking and `BlockedCard`

The chat handlers run the guardrail check on the `guardrails_config_id`, for the input and for the output.

- Blocked **input**: the stored answer becomes `GUARD_BLOCK_COPY[guard]["input"]`, and the trace stores
  `latency_ms = {route: "blocked", blocked: true, blocked_by_guard, blocked_on}`. Metrics are not enqueued.
- Blocked **output**: the streamed answer is replaced, the same blocked latency keys are merged in, and
  metrics are not enqueued.
- `GUARD_BLOCK_COPY` covers `ban_list`, `pii_check` and `toxic_language`, each with an `input` and an `output`
  sentence (`routes/chat.py:118-134`). The SSE `blocked` frame also carries `blocked_title`
  (`"Banned keyword"` / `"Personal information"` / `"Toxic language"`, else the guard name, else
  `"Guardrail"`).
- The guardrails service names its guard `ban-list`, while the stored config uses `ban_list`.
  `rag_shared/guardrails_client.py` maps `_` to `-`, so the check reaches the service. Before that fix every
  check returned 404, the client read a non-200 as "passed", and no guardrail ever blocked anything.

`BlockedCard` (`ChatPage.tsx:45-73`) maps `blocked_by_guard` to an icon, a title and a tone: `ban_list` → 🚫
`Banned keyword`, `pii_check` → 🔒 `Personal information`, `toxic_language` → ⚠️ `Toxic language`. Any other
guard falls back to 🛡️ with the guard name as the title. The phase label is `Response blocked` when
`blocked_on === "output"`, otherwise `Input blocked`. The body is the server `content`, with a generic hint as
the fallback. The CSS classes are `chat-blocked-card` and `chat-blocked-card--<tone>`. The server-supplied
`blocked_title` is not used by the UI. A card renders whenever `m.blocked` is true or the stored trace route is
`blocked`.

---

## 7. Non-Streaming `POST /chat`

Returns `ChatResponse`: `message_id`, `session_id`, `answer`, `sources`
(`[{source_locator, chunk_index, rerank_score}]`, taken from the reranked chunks), `trace_id` and
`metrics_status`. Guardrails run the same way: an input block returns early with empty sources, and an output
block rewrites the answer.

The Chat page never calls this route. The assistant surface does: `POST /api/assistants/{slug}/chat` returns
the same shape, and `POST /v1/assistants/{slug}/chat/completions` wraps it in the OpenAI shape. Those routes
delegate to this handler, so guardrails, retrieval, rerank, generation, persistence and metrics are not
duplicated.

---

## 8. Metrics Polling

After a turn, the page polls `GET /chat/messages/{message_id}/metrics` every **2500 ms**, up to **40**
attempts, and tolerates HTTP 404 for the first **8** attempts (the worker may not have created the row yet)
(`ChatPage.tsx:272-293`). It skips polling for blocked turns and for messages whose `metrics_status` is
`skipped` or `failed` (`ChatPage.tsx:144-156`). When a poll returns `completed`, the historical stats are
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
(`rag-retrieval-chat-manager/backend/apps/rag-api/src/rag_api/routes/assistants.py:105-160`).

### 9.1 Sessions and message deletion

- Session **creation** is implicit: `_persist_chat_turn` reuses `session_id` when the row exists and otherwise
  creates a session. There is no `POST /chat/sessions`.
- `ChatSessionItem` keys: `session_id`, `created_at`, `last_message_at`, `preview`, `message_count`. `preview`
  is the first user message truncated to 120 chars. Because `list_sessions` inner-joins `chat_messages`, a
  session with no messages is never listed (`chat_repository.py:120-155`).
- `ChatMessageItem` keys: `id`, `role`, `content`, `created_at`, `trace` (`retrieval_mode`, `rerank_enabled`,
  `generation_model`, `route`), `sources`, `metrics_status`, `blocked`, `blocked_by_guard`, `blocked_on`.
  `route` is read from the stored trace `latency_ms.route`, and `blocked` is true when `latency_ms.blocked` is
  set or that route is `blocked` (`routes/chat.py:795-823`).
- `DELETE /chat/messages/{id}` returns `deleted_message_ids` covering the reply and its question. The page
  drops them from state and clears their cached metrics (`ChatPage.tsx:324-350`).
- > **Working-tree gap.** Both DELETE handlers call `ChatRepository.soft_delete_session` and
  > `ChatRepository.soft_delete_message_turn`, and read `ChatMessage.deleted_at`
  > (`routes/chat.py:820-845`). Neither the repository nor the chat model defines them, so both endpoints
  > currently raise `AttributeError` (HTTP 500). The contracts above are what the routes declare.

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
   into a text group and an image group (`generation_core/generator.py:97`, `rag_shared/chunk_utils.py:8-47`).
2. The text chunks go to the chat model with the numbered-context RAG prompt (`generator.py:28-44`,
   `prompt_builder.py:30-45`).
3. The image chunks go to the vision model, named by the request `vision_model` or `settings.vision_model`,
   default **`groq-vision`**, as an OpenAI multimodal message: one instruction text part, then per image a
   `[Image N] Source: <locator>` caption part and a `{"type": "image_url", "image_url": {"url": <data URI>}}`
   part. At most **3** images are attached, with `max_tokens=1024` and `temperature=0.2`
   (`generation_core/vision_generator.py:21-70`).
4. When both a text answer and a vision answer exist, a third call to the `fusion_model` merges them.
   Otherwise the single available answer is returned. With no relevant chunks the answer is
   `NO_SOURCES_ANSWER`: `"I could not find any relevant sources in the knowledge base to answer this
   question."` (`prompt_builder.py:5-7`).
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
