# 03 — Interactive RAG Chat & Synthesis Page

**Last updated:** 2026-09-17

## 1. Executive Summary & Page Purpose
The **Chat page** (`frontend/src/pages/ChatPage.tsx`, route `/chat`) is the conversational playground for a RAG pipeline. It selects a pipeline record, a guardrails config and per-query retrieval overrides, streams the answer over Server-Sent Events, renders cited sources, and then polls per-message RAGAS metrics.

- Transport: the retrieval API at `RAG_API_URL = VITE_RAG_API_URL ?? "http://localhost:8001"` (`frontend/src/api.ts:5`). Every request sends `X-API-Key` when `VITE_RAG_API_KEY` (falling back to `VITE_API_KEY`) is set (`api.ts:7,16-18,733-737`). All routes in that app sit behind `Depends(verify_api_key)` (`rag-retrieval-chat-manager/backend/apps/rag-api/src/rag_api/main.py:62`).
- There is **no image attachment control** in the chat UI: the composer is a single text input plus `Send` (`ChatPage.tsx:1024-1040`). Multimodal content is handled server-side over image chunks that an ingestion-time multimodal pipeline already stored (see §4.4).
- There is **no "Guardrails: On" toggle**. The sidebar exposes a Guardrails `<select>` whose default option is `None`, plus every saved config (inactive ones are suffixed `(inactive)`) (`ChatPage.tsx:594-626`).
- Chat users pick a pipeline by record from the selector; the pipeline's `description` is the human-facing identity used in the Pipelines page (doc 02).

---

## 2. UI Layout & Visual Components

```
+----------------------------------------------------------------------------------------------------------+
| Conversations            |  [Mode: Hybrid][Limit: 20][Rerank: on][Top K: 5]                              |
| [+ New]                  |  [Strategy: Auto][Classifier: LLM][Max Loops: 3]                              |
| ------------------------ |  session: <id prefix> or "New Session"                                        |
| Pipeline  [select]       |  You                                                            14:22         |
|  Strategy: hybrid        |  Find senior AI engineers with PyTorch, Neo4j and Qdrant experience.          |
|  Embedding: nvidia-...   |                                                                               |
|  Sparse: Qdrant/bm25     |  Assistant  [Normal RAG]                                         14:22        |
| ------------------------ |  Based on the indexed resumes, **Alex Chen** is a Senior AI Engineer...       |
| Guardrails [select: None]|                                                                               |
|  Mode: input             |  Faithful: 92%  Relevance: 88%  Ctx Prec: 75%  2 sources                      |
|  Guards: ban_list, ...   |  resume_alex_chen.pdf (Score: 0.94)                                           |
| ------------------------ |  resume_elena_rostova.pdf (Score: 0.81)                                       |
| Chat History             |  -------------------------------------------------------------------------    |
|  <preview>               |  [ Type your message...                                        ] [ Send ]     |
|  12 messages · 14:22  ⋯  |                                                                               |
+----------------------------------------------------------------------------------------------------------+
|  Evaluation & Metrics (collapsible): Golden Dataset Eval | Eval Progress | Historical Metrics            |
+----------------------------------------------------------------------------------------------------------+
```

- Sidebar header `Conversations` + `+ New` button (`ChatPage.tsx:557-563`); `+ New` only clears the local session/messages state — the server creates the session on the next message (`ChatPage.tsx:301-306`).
- Session rows show `preview` (the first user message truncated to 120 chars in the repository) or `Session <first 8 chars>`, the message count, and the last message time (HH:MM); a kebab menu offers **Delete conversation** (`ChatPage.tsx:654-690`, `rag_db/repositories/chat_repository.py:150`).
- Messages are sorted by `created_at` with a user-before-assistant tie-break for identical timestamps (`ChatPage.tsx:534-547`).
- Assistant messages render through `MarkdownMessage` (`react-markdown` + `remark-gfm` + `remark-math` + `rehype-katex`, `frontend/src/components/MarkdownMessage.tsx:1-5`); user text is rendered verbatim.
- Route badge per assistant message: `greeting`, `normal`, `simple_rag_auto`, `self_corrective`, `self_corrective_auto`, `blocked` (`ChatPage.tsx:844-855`).
- Source citations show **only the first 3** reranked chunks as `📄 <source_locator> (Score: <rerank_score to 2dp>)` plus an `N sources` badge (`ChatPage.tsx:975-990`). There is no chunk inspector drawer and no chunk-index display.
- While streaming, the pending assistant bubble shows the current `status` message with a pulsing dot, then the streamed markdown with a blinking cursor (`ChatPage.tsx:998-1020`).
- Collapsible **Evaluation & Metrics** panel: golden-dataset picker + `Run Pipeline Eval`, live eval-run progress (status, `items_completed/items_total`, numeric aggregate metrics from the `retrieval`/`reranker`/`generation` blocks with a leading `mean_` stripped), and historical averages computed client-side from `GET /chat/stats?limit=10` (`ChatPage.tsx:1044-1150`).

---

## 3. Streaming Chat Protocol & Guardrail Feedback

### 3.1 Request
`POST /chat/stream` (`routes/chat.py:493`), body = `ChatRequest` (`routes/chat.py:22-24`) = the shared `PipelineRequest` plus `session_id` and `guardrails_config_id`.

The page builds the payload as (`ChatPage.tsx:371-397`):

| Key | Value sent by the page |
|---|---|
| `query` | message text |
| `session_id` | active session or `null` for a new chat |
| `retrieval_mode` | `hybrid` \| `dense` \| `sparse` (forced to `dense` for image-only multimodal pipelines) |
| `retrieve_limit` | toolbar Limit (1–50, default 20) |
| `rerank_enabled` | toolbar Rerank checkbox (default on) |
| `top_k` | toolbar Top K (1–20, default 5) |
| `router_enabled`, `router_mode`, `rag_mode`, `self_corrective_max_loops` | toolbar Strategy / Classifier / RAG Mode / Max Loops |
| `guardrails_config_id` | selected guardrails config id, omitted when `None` |
| `collection`, `embedding_model`, `sparse_embedding_model` | copied from the selected pipeline record |

Server-side defaults come from `PipelineConfig`: `retrieval_mode=hybrid`, `retrieve_limit=20`, `rerank_enabled=true`, `top_k=5` (`rag_core/schemas.py:9-13`); the generation model falls back to `settings.chat_model` (`routes/chat.py:514`).

### 3.2 SSE framing and event contract
Framing: `media_type="text/event-stream"`, headers `Cache-Control: no-cache` and `X-Accel-Buffering: no` (`routes/chat.py:757-761`). Every frame is `data: <json>\n\n`; the generator runs in a worker thread and bridges chunks through a queue so OpenTelemetry context survives (`routes/chat.py:520-521,745-755`).

| `type` | Payload keys | Emitted when |
|---|---|---|
| `status` | `message` | `"Checking guardrails..."` before an input guardrail check (`routes/chat.py:531`); `"Processing message"` on the greeting route (`routes/chat.py:587`) |
| `token` | `content` | Greeting route emits one character per frame with a 10 ms sleep (`routes/chat.py:589-591`); the RAG route forwards each pipeline event as `{type, message?, content?, metadata?}` (`routes/chat.py:662-670`) |
| `done` | `metadata` | Greeting: `{sources: [], route: "greeting", session_id, message_id}` (`routes/chat.py:618-619`); RAG: the pipeline's own done metadata (`answer`, `sources`, `retrieved_chunks`, `reranked_chunks`, `latency_ms`, `session_id`, `message_id`) (`routes/chat.py:662-670,676-684`) |
| `session` | `session_id`, `message_id`, `route`, `metrics_status` | After the DB write. `route` is `blocked` on an output block, otherwise the effective route (`greeting`, `normal`, `self_corrective`, `simple_rag_auto`, `self_corrective_auto`) and `metrics_status` is `skipped` when blocked (`routes/chat.py:731-733,628-630`) |
| `blocked` | `content`, `blocked_by_guard`, `blocked_on`, `blocked_title`, `session_id`, `message_id`, `route`, `metrics_status` | Input or output guardrail block (`routes/chat.py:151-171,558-561,728-730`) |
| `error` | `content` | Any exception in the worker, including `str(e)` (`routes/chat.py:736`) |

The client splits the byte stream on `\n\n`, keeps only lines starting with `data: `, and `JSON.parse`s each into a `ChatStreamEvent` whose declared fields are `type`, `message`, `content`, `session_id`, `message_id`, `route`, `metrics_status`, `blocked_by_guard`, `blocked_on`, `blocked_title`, `metadata` (`api.ts:710-765`). The page then prefers the `session` event's real ids over the `done` metadata, and marks a turn `blocked` when a `blocked` event arrived (`ChatPage.tsx:410-467`).

> **Working-tree gap.** The RAG branch of `/chat/stream` calls `pipeline.stream_chat(...)` / `pipeline.stream_chat_self_corrective(...)` (`routes/chat.py:648-655`), but `RAGPipeline` only defines `retrieve`, `rerank`, `chat` and `generate` (`rag_core/pipeline.py:27-145`), and `config.rag_mode` read at `routes/chat.py:629` is not a field of `PipelineConfig` (`rag_core/schemas.py:8-19`). The `router_enabled` / `router_mode` / `rag_mode` / `self_corrective_max_loops` keys the UI sends are also not declared on `PipelineRequest`, so pydantic drops them and `getattr(body, "router_enabled", False)` is always `False` (`routes/chat.py:564-576`). As the code stands the RAG branch raises `AttributeError`, is caught by the handler, and the client receives an `error` event instead of tokens. The greeting and guardrail-block branches are self-contained and emit the events above.

### 3.3 Guardrail blocking and `BlockedCard`
`_run_guardrails` (`routes/chat.py:295-354`) only runs when `guardrails_config_id` is present. It skips a phase the config's `mode` does not cover, calls the guardrails service, treats the first guard whose result has `validation_passed == false` as blocking (`rag_shared/guardrails_client.py:46-51`), records a guardrails trace row, and returns `(is_blocked, blocking_guard, results)`.

- Blocked **input**: the stored answer becomes `GUARD_BLOCK_COPY[guard]["input"]` (or `"<Phase> blocked by guardrail: <guard>."`), the trace stores `latency_ms = {route: "blocked", blocked: true, blocked_by_guard, blocked_on}` and metrics are **not** enqueued (`routes/chat.py:529-561,142-148`).
- Blocked **output**: the streamed answer is replaced, the same blocked latency keys are merged in, and metrics are not enqueued (`routes/chat.py:676-697`).
- `GUARD_BLOCK_COPY` covers `ban_list`, `pii_check`, `toxic_language`, each with an `input` and an `output` sentence (`routes/chat.py:118-136`). The SSE `blocked` frame additionally carries `blocked_title` (`"Banned keyword"` / `"Personal information"` / `"Toxic language"`, else the guard name, else `"Guardrail"`).
- `BlockedCard` (`ChatPage.tsx:45-72`) maps `blocked_by_guard` to an icon/title/tone: `ban_list` → 🚫 `Banned keyword`, `pii_check` → 🔒 `Personal information`, `toxic_language` → ⚠️ `Toxic language`; any other guard falls back to 🛡️ with the guard name as the title. The phase label is `Response blocked` when `blocked_on === "output"`, otherwise `Input blocked`. The body is the server `content`, falling back to a generic hint. The CSS classes are `chat-blocked-card` / `chat-blocked-card--<tone>`; the server-supplied `blocked_title` is not used by the UI. A card is rendered whenever `m.blocked` is true or the stored trace route is `blocked` (`ChatPage.tsx:914-924`).

### 3.4 Non-streaming `POST /chat`
Returns `ChatResponse` (`routes/chat.py:33-40,483-491`): `message_id`, `session_id`, `answer`, `sources` (`[{source_locator, chunk_index, rerank_score}]` taken from the reranked chunks), `trace_id`, `metrics_status`. Guardrails run the same way (input block returns early with empty sources; output block rewrites the answer) (`routes/chat.py:378-421`).

### 3.5 Metrics polling
After a turn, the page polls `GET /chat/messages/{message_id}/metrics` every **2500 ms**, up to **40** attempts, tolerating HTTP 404 for the first **8** attempts (the worker may not have created the row yet) (`ChatPage.tsx:277-299`). It skips polling for greetings, blocked turns and messages whose `metrics_status` is `skipped` or `failed` (`ChatPage.tsx:148-163`). When a poll returns `completed` the historical stats are refreshed (`ChatPage.tsx:284-290`).

---

## 4. Backend APIs & Contracts

All paths relative to the retrieval API base URL; auth via `X-API-Key` header or `api_key` query parameter.

| Method | Endpoint | Description | Request / Response |
|---|---|---|---|
| `POST` | `/chat` | Non-streaming RAG turn (persists user + assistant messages) | `ChatRequest` → `ChatResponse` |
| `POST` | `/chat/stream` | SSE token stream | `ChatRequest` → `text/event-stream` |
| `GET` | `/chat/sessions?limit=50` | Sessions, newest activity first | → `{limit, count, items: [ChatSessionItem]}` |
| `GET` | `/chat/sessions/{session_id}/messages` | Ordered message history with route, sources and metrics status | → `{session_id, count, items: [ChatMessageItem]}`; 404 when the session is unknown |
| `DELETE` | `/chat/sessions/{session_id}` | Deletes a conversation | → `204 No Content` |
| `DELETE` | `/chat/messages/{message_id}` | Deletes one assistant turn **and its preceding question** | → `{session_id, deleted_message_ids: [...]}`; 404 if unknown/already deleted |
| `GET` | `/chat/messages/{message_id}/metrics` | RAGAS metrics for one assistant message | → `MetricsResponse`; 404 while no row exists |
| `GET` | `/chat/stats?limit=20` | Recent assistant messages with metrics | → `{limit, count, items: [ChatStatItem]}`; `limit` must be 1–100 or 422 |

### 4.1 Sessions & message deletion
- Session **creation** is implicit: `_persist_chat_turn` reuses `session_id` when the row exists and otherwise creates a session with the request's `source_type` / `source_id` (`routes/chat.py:256-262`). There is no `POST /chat/sessions`.
- `ChatSessionItem` keys: `session_id`, `created_at`, `last_message_at`, `preview`, `message_count` (`routes/chat.py:84-90`). `preview` is the first user message truncated to 120 chars, `message_count` only counts messages, and because `list_sessions` inner-joins `chat_messages` a session with no messages is never listed (`chat_repository.py:120-155`).
- `ChatMessageItem` keys: `id`, `role`, `content`, `created_at`, `trace` (`retrieval_mode`, `rerank_enabled`, `generation_model`, `route`), `sources`, `metrics_status`, `blocked`, `blocked_by_guard`, `blocked_on` (`routes/chat.py:105-116,862-884`). `route` is read from the stored trace `latency_ms.route`, and `blocked` is true when `latency_ms.blocked` is set or that route is `blocked`.
- `DELETE /chat/messages/{id}` returns `deleted_message_ids` covering the reply and its question; the page drops them from state and clears their cached metrics (`ChatPage.tsx:324-350`).
- > **Working-tree gap.** Both DELETE handlers call `ChatRepository.soft_delete_session` / `soft_delete_message_turn` and read `ChatMessage.deleted_at` (`routes/chat.py:889-919`), but neither the repository (`rag_db/repositories/chat_repository.py`) nor the model (`rag_db/models/chat.py`) defines them, so the endpoints currently raise `AttributeError` (HTTP 500). The contracts above are what the routes declare.

### 4.2 Per-message metrics
`MetricsResponse` (`routes/chat.py:42-53`): `message_id`, `status` (`pending` | `completed` | `failed`), `faithfulness`, `answer_relevancy`, `context_precision`, `context_recall`, `kendall_tau`, `mrr`, `ndcg`, `metrics`, `error_message`. The three ranking scores are pulled from `metrics.raw_ragas["reranker"]`; `metrics` is the staged RAGAS payload and is `null` unless `raw_ragas` contains `retrieval`, `reranker` or `generation` blocks (`routes/chat.py:205-229`). Rows are created with status `pending` and a queued `eval_worker.tasks.compute_chat_metrics` job when `settings.ragas_enabled` and `settings.chat_metrics_async` are true (defaults `true`/`true`); otherwise `metrics_status` is `skipped` (`routes/chat.py:283-291`, `rag_shared/config.py:42-43`).

### 4.3 Chat stats
`ChatStatItem` (`routes/chat.py:56-74`) returns `message_id`, `session_id`, `query`, `answer`, `faithfulness`, `answer_relevancy`, `context_precision`, `context_recall`, `kendall_tau`, `mrr`, `ndcg`, `metrics`, `metrics_status`, `computed_at`, `latency_ms`, `retrieval_mode`, `rerank_enabled`, `generation_model`, `created_at`. The page requests `limit=10` and averages `faithfulness` and `answer_relevancy` over items that have either value (`ChatPage.tsx:242-248,1126-1150`).

### 4.4 Multimodal image inputs
Images are **never uploaded from the chat UI**; they travel with retrieval results.

1. When a query runs against a collection holding image chunks (chunk `type == "image"`, content starting with `data:image/`, or `image_base64` + `mime_type` metadata), `Generator.generate` splits the reranked chunks into text and image groups (`generation_core/generator.py:97`, `rag_shared/chunk_utils.py:8-47`).
2. Text chunks go to the chat model (default `llama-3.3-70b-versatile`) with the numbered-context RAG prompt (`generator.py:28-44`, `prompt_builder.py:30-45`).
3. Image chunks go to the vision model — request `vision_model` or `settings.vision_model`, default **`groq-vision`** — as an OpenAI multimodal message: one instruction text part, then per image a `[Image N] Source: <locator>` caption part followed by `{"type": "image_url", "image_url": {"url": <data URI>}}`; at most **3** images are attached, `max_tokens=1024`, `temperature=0.2` (`generation_core/vision_generator.py:21-70`, `rag_shared/config.py:37,39-40`).
4. When both a text and a vision answer exist, a third call to `fusion_model` (request override or `settings.fusion_model`, default `llama-3.3-70b-versatile`) merges them; otherwise the single available answer is returned (`generator.py:125-143`, `prompt_builder.py:47-62`). With no relevant chunks the answer is `NO_SOURCES_ANSWER` — `"I could not find any relevant sources in the knowledge base to answer this question."` (`prompt_builder.py:5-7`).
5. The page forces `retrieval_mode = "dense"` when the selected pipeline's `modality` is `image`, or its strategy is `multimodal` without a sparse model, because image-only indexes have no sparse vectors (`ChatPage.tsx:390-397`).
6. `vision_model` and `fusion_model` are accepted request overrides on `ChatRequest` but the chat UI never sets them; only `PipelineRequest.generation_model` / `vision_model` / `fusion_model` can be passed by API clients (`rag_core/schemas.py:33-35`).
