# 05 — Real Time Monitoring Page

**Last updated:** 2026-09-17

## 1. Executive Summary & Page Purpose
The **Real Time Monitoring** page is `frontend/src/pages/EvaluationsPage.tsx`, mounted at route `/evaluations` with sidebar label "Real Time Monitoring" (`frontend/src/components/AppLayout.tsx:29`, `:120`). It shows *recent* chat turns that have an async quality-metrics row and their pipeline latencies, read from a single endpoint: `GET /chat/stats?limit=N` (`EvaluationsPage.tsx:111`).

Scope corrections against the previous version of this document:
- The page is **not** `TrackingPage.tsx`. `/tracking` is a different page ("Pipeline Tracking": pipeline runs, scraper crawl/scrape jobs) documented separately in `07_tracking_and_traces_page.md`.
- It is a **manual-refresh table**, not a live stream: there is no SSE endpoint and no polling interval in this page (Section 6).
- The page shows no percentile, cache-hit, cost or token aggregates. The backend has no `p95`, `percentile` or `cache_hit` code at all, and the routes `/tracking/stream` and `/tracking/latency-breakdown` do not exist (the routes package contains only `chat`, `evaluate`, `prompts`, `guardrails`, `guardrails_evaluate`, `health`, `knowledge`, `retrieve`, `rerank`, `search`, `generate`).
- The previous sample payload for `/tracking/latency-breakdown` was fictional; the real payload shape is in Section 3.

---

## 2. Key Views & Metrics

```
+---------------------------------------------------------------------------------------------------------+
|  Real Time Monitoring                                     [ Open Langfuse ] [ Open Phoenix ] [ Refresh ] |
|  Monitor LLM response quality metrics across chats and pipeline configurations.                          |
+---------------------------------------------------------------------------------------------------------+
|  [ Latency View ] [ Metrics View ]                                        Limit  [ 10 | 20 | 50 | 100 ]  |
+---------------------------------------------------------------------------------------------------------+
|  Message ID / Query          | Time | Retrieval (ms) | Rerank (ms) | Generation (ms) | Total (ms) | Config |
|  ...                          | 5m   | 124            | 185         | 810             | 1119       | Mode/Rerank/Model |
+---------------------------------------------------------------------------------------------------------+
|  In Metrics View the four value columns become:                                                          |
|  Retrieval (Context Precision / Recall, %) | Reranker (MRR / NDCG / Kendall Tau) |                      |
|  Generation (Faithfulness / Relevancy, %)  | Status                             | Config                |
+---------------------------------------------------------------------------------------------------------+
|  [ Previous ]  Page N of M  [ Next ]        (10 rows per page, client-side)                              |
+---------------------------------------------------------------------------------------------------------+
```

Row content (`EvaluationsPage.tsx:279-373`):
- Message ID (first 8 characters) and the trace query, clamped to two lines; `—` when the query is null.
- A `test` or `prod` tag sits next to the message id, from `item.trace_mode` (`:307-319`). It is two-toned as well as two-worded — `trace-tag--test` and `trace-tag--prod` differ in border and text colour — so the modes are distinguishable at a glance and not by reading alone. A row written before migration `004` has a null mode and renders **no tag**, rather than a guess at one.
- Time: `created_at` formatted relative (`formatRelativeTime`).
- Latency View columns read `latency_ms` with fallbacks: `retrieve || retrieval`, `reranking || rerank`, `generate || generation`, `total`, rendered as `<n> ms`; missing keys render `—`.
- Metrics View cells read the staged `metrics` object (or the latest CRAG iteration when present):
  - Retrieval: `retrieval.context_precision`, `retrieval.context_recall` (percent, `ScoreBar`).
  - Reranker: `reranker.mrr`, `reranker.ndcg`, `reranker.kendall_tau` (total `—` when all three are null).
  - Generation: `generation.faithfulness`, `generation.answer_relevancy` (percent, `ScoreBar`).
  - Status badge: `metrics_status` — `completed` green, `pending` amber, anything else (`failed`, `skipped`) red.
- Config column: `retrieval_mode`, `rerank_enabled` (Yes/No) and `generation_model` when set.
- Score formatting: percentages as `(v*100).toFixed(0)%`, other numbers as `toFixed(3)`, null/NaN as `—` (`:21-24`); `ScoreBar` is green at ≥0.85, blue at ≥0.65, red below (`:26-35`).
- CRAG rows: when `metrics.generation.sc_iterations[]` is non-empty (Metrics View only), a `CRAG · N loop(s)` badge appears from `latency_ms.sc_loops` or the iteration count, and a row expander renders one sub-row per iteration (`loop`, `query`, the three metric groups). No backend producer of `sc_iterations`/`sc_loops` exists (Section 4.6), so this never triggers with the current pipeline.
- Controls: view toggle "Latency View" (default) / "Metrics View", `Limit` selector 10/20/50/100 with default 20, header "Refresh" button, and **two** header links out to the backends: "Open Langfuse" to `VITE_LANGFUSE_TRACES_URL` (fallback `https://cloud.langfuse.com`) and "Open Phoenix" to `VITE_PHOENIX_URL` (fallback `https://app.phoenix.arize.com`). Both read the env var at build time, so a deep link can point straight at the traces instead of a landing page. Pagination is client-side at 10 rows per page.
- States: error alert on failure, "Loading...", and "No stats available for the selected limit." when the response has no items.

---

## 3. Backend APIs & Contracts

| Method | Endpoint | Description | Request / Response |
|---|---|---|---|
| `GET` | `/chat/stats?limit=N` | Recent assistant turns with metrics + trace summary; **the only endpoint this page calls** | `ChatStatsResponse` |
| `GET` | `/chat/messages/{message_id}/metrics` | Per-message metric detail; used by the Chat page, not by this page | `MetricsResponse` (404 when no metrics row) |
| `GET` | `/evaluate/stats?limit=N` | Offline golden-evaluation run aggregates; not consumed by this page (no frontend caller) | `EvaluationStatsResponse`; limit must be 1–100 else 422 |
| `GET` | `/guardrails/stats` | Guardrail interception stats; not consumed by this page | `StatsResponse` |

Notes:
- `/chat/stats` defaults to `limit=20` and has no server-side range validation (`routes/chat.py:802-806`); `/evaluate/stats` defaults to `limit=20` and rejects values outside 1–100 (`routes/evaluate.py:398-407`).
- Rows come from `ChatRepository.list_recent_metrics_stats(limit)`: inner join `chat_message_metrics` + `chat_messages` (role = `assistant`), outer join `chat_pipeline_traces`, ordered by `chat_messages.created_at DESC` (`libs/database/src/rag_db/repositories/chat_repository.py:169-178`). Only turns for which an async metrics job was enqueued appear; blocked turns are excluded (metrics are never enqueued for them).

Sample payload (`GET /chat/stats?limit=20`):
```json
{
  "limit": 20,
  "count": 1,
  "items": [
    {
      "message_id": "3f0c...",
      "session_id": "9a12...",
      "query": "What is the onboarding process?",
      "answer": "According to the handbook ...",
      "faithfulness": 0.91,
      "answer_relevancy": 0.87,
      "context_precision": 0.62,
      "context_recall": 0.75,
      "kendall_tau": 0.44,
      "mrr": 1.0,
      "ndcg": 0.83,
      "metrics": {
        "retrieval": { "context_precision": 0.62, "context_recall": 0.75 },
        "reranker": { "mrr": 1.0, "ndcg": 0.83, "kendall_tau": 0.44 },
        "generation": { "faithfulness": 0.91, "answer_relevancy": 0.87 }
      },
      "metrics_status": "completed",
      "computed_at": "2026-09-16T08:31:12Z",
      "latency_ms": { "retrieve": 124, "rerank": 185, "generate": 810, "total": 1119 },
      "retrieval_mode": "hybrid",
      "rerank_enabled": true,
      "generation_model": "llama-3.3-70b-versatile",
      "created_at": "2026-09-16T08:31:02Z"
    }
  ]
}
```

Model definitions: `ChatStatItem` / `ChatStatsResponse` (`routes/chat.py:56-73`), `MetricsResponse` (`routes/chat.py:42-53`). `ChatStatItem.metrics` is `raw_ragas` when it contains any of `retrieval` / `reranker` / `generation`, otherwise `null` (`_staged_metrics`, `routes/chat.py:197-203`). `kendall_tau`, `mrr` and `ndcg` are not database columns; the API derives them from `raw_ragas["reranker"]` (`_reranker_metric`, `routes/chat.py:205-210`, `:788-790`).

---

## 4. How the Metrics Are Computed
### 4.1 Enqueue path (write time)
When a chat turn completes, the API enqueues metrics only if `settings.ragas_enabled` and `settings.chat_metrics_async` are true (both default `true`, `libs/shared/src/rag_shared/config.py:43-44`): it inserts a `chat_message_metrics` row with status `pending` and pushes `eval_worker.tasks.compute_chat_metrics` onto the RQ queue `rq_eval_queue` (default `"eval"`, `config.py:18`) — `routes/chat.py:283-289`. Blocked turns call the same persist helper with `enqueue_metrics=False`, so their `metrics_status` stays `skipped` (`routes/chat.py:404`, `:169`). There is no sampling/rate limit: every eligible turn is queued.

`eval-worker` (`apps/eval-worker/src/eval_worker/main.py:15-18`) consumes that queue.

### 4.2 Computation (`apps/eval-worker/src/eval_worker/tasks.py:44-101`)
`compute_chat_metrics(message_id)` loads the trace plus the assistant message, calls `eval_core.chat_metrics.compute_chat_pipeline_metrics(settings, question=…, answer=…, retrieved_chunks=…, reranked_chunks=…)` with the stored `retrieved_chunks` / `reranked_chunks`, flattens the result with `flatten_chat_metrics`, and calls `ChatRepository.update_metrics(..., status="completed")`. It then emits a `rag.pipeline.metrics` span carrying the latency map, the scores and the chunks (`tasks.py:44-101`).

That span is **parented under the turn's own span**, using the `otel_trace_id` and `otel_span_id` stored on the trace row, and it carries the turn's `trace_mode`. The scores therefore land inside the trace of the question they score, instead of producing a second trace for the same question. A trace row written before migration `004` has no ids, and the span opens its own trace instead. Any exception is caught and stored as status `failed` with `error_message`.

### 4.3 Metric definitions (`libs/eval-core/src/eval_core/chat_metrics.py`)
- Guard: if `settings.ragas_enabled` is false, the function returns empty stages (`:52-53`).
- Retrieval (pre-rerank chunks): RAGAS `ContextPrecision` and `ContextRecall`, called with `reference` = the assistant answer because live chat has no gold labels (`ragas_client.calculate_retrieval_ragas_async`, `:117-161`). Image chunks contribute their title/locator/`Image chunk N` as context text instead of the base64 payload (`chat_metrics.py:17-28`). Skipped when the answer or the context list is empty (`:66-73`).
- Reranker: `kendall_tau_rank_correlation(before=retrieved, after=reranked)` (`:110-112`) plus `compute_rerank_metrics(..., k_values=[5, 10])` for `mrr` and `ndcg` (`:105-108`). Because there is no gold set, the "expected sources" are spoofed by a Jaccard-style token-overlap heuristic: chunk source locators whose content overlaps the answer tokens by at least 50% of the best overlap are treated as expected (`:87-103`).
- Generation (post-rerank chunks): RAGAS `Faithfulness` and `AnswerRelevancy` (`ragas_client.calculate_generation_ragas_async`, `:165-240`, called from `chat_metrics.py:75-81`).
- Flattening: `flatten_chat_metrics` maps the staged dict onto `context_precision`, `context_recall`, `faithfulness`, `answer_relevancy`, `kendall_tau`, `mrr`, `ndcg` and keeps the nested structure as `raw_ragas` (`:142-152`).
- Persistence: `ChatMessageMetrics` stores `faithfulness`, `answer_relevancy`, `context_precision`, `context_recall`, `raw_ragas`, `status`, `error_message`, `computed_at` (`libs/database/src/rag_db/models/chat.py:64-79`); `update_metrics` writes only those four scores plus `raw_ragas` (`chat_repository.py:88-105`), which is why the reranker values are served out of `raw_ragas`.

### 4.4 Latency keys
Written by the pipeline: `retrieve`, `rerank`, `generate`, `total` (`libs/rag-core/src/rag_core/pipeline.py:59-72`, `:110-119`), extended by the generator with `generate_text`, `generate_vision`, `generate_fusion`, `generate_total` (`libs/generation-core/src/generation_core/generator.py:112-143`). `generate` equals `generate_total`. Blocked turns store only `route`, `blocked`, `blocked_by_guard`, `blocked_on` (`routes/chat.py:142-148`), so every latency column renders `—` for them. The worker also tries to read `prompt_tokens` / `completion_tokens` out of `latency_ms` for the emitted trace metadata (`tasks.py:73-74`), but nothing in the libraries writes those keys.

### 4.5 Live-sampling and RAGAS availability
There is no sample-rate configuration or bounded sampling anywhere in the backend — metrics are computed for all enqueued turns, by a RAGAS judge LLM and embedding model built from the LiteLLM proxy settings (`ragas_client.py:21-86`, judge model `ragas_judge_model`, default `llama-3.3-70b-versatile`, `config.py:42`). Non-finite or missing scores become `None` (`_score_value`, `ragas_client.py:89-105`), so absent values are normal and render as `—`. Error tolerance differs by stage: the generation metrics are gathered with `return_exceptions=True` (`ragas_client.py:223`), so a failing judge call yields a missing score, whereas retrieval precision/recall are awaited directly (`ragas_client.py:147-161`) and a judge exception there propagates and fails the whole metrics job (recorded as `failed` by the worker).

### 4.6 CRAG/self-corrective iterations
The page expects `metrics.generation.sc_iterations[]` and `latency_ms.sc_loops` (`EvaluationsPage.tsx:230-239`, `:296-301`), but no backend code produces either key: the only occurrence of `sc_iterations` in the backend is the worker reading `latency_ms["sc_iterations"]` (`tasks.py:65`). The CRAG loop expander therefore stays inactive.

---

## 5. Known Implementation Caveats (verified in the current tree)

The `sc_iterations` mismatch recorded in earlier revisions of this document is **fixed**. `compute_chat_pipeline_metrics` accepted only `settings`, `question`, `answer`, `retrieved_chunks` and `reranked_chunks`, while the worker passed a seventh `sc_iterations` argument. Every call raised `TypeError`, the worker caught it, and every row landed on `failed` with no scores. The extra argument is gone and the call now matches the signature (`tasks.py:74-80`, `chat_metrics.py:121-128`), so Metrics View shows real scores.

Two caveats remain, both narrower:

- **The CRAG expander is still dead.** The page reads `metrics.generation.sc_iterations[]` and `latency_ms.sc_loops` (`EvaluationsPage.tsx:230-239`, `:296-301`), and nothing in the backend produces either key. Only the expander is affected; the ordinary score columns work.
- **The token counts are always absent.** The worker reads `prompt_tokens` / `completion_tokens` out of `latency_ms` to put them on the emitted span (`tasks.py:85-86`), but no library writes those keys. They are silently dropped, not an error.

---

## 6. Refresh & Polling Behaviour
- The page calls `GET /chat/stats` on mount (pages are mounted persistently, so this happens when the app loads), whenever `limit` changes (`EvaluationsPage.tsx:108-122`), and on the explicit **Refresh** button.
- There is no `setInterval`/SSE/websocket in this page: values only change when the operator refreshes or changes the limit. (The separate Tracking page polls every 300 000 ms — `pages/TrackingPage.tsx:81-85`; the Chat page polls `/chat/messages/{id}/metrics` per message until status is `completed`/`failed`, max 40 attempts — `pages/ChatPage.tsx:283-287`.)
- **Open Langfuse** and **Open Phoenix** link out to the configured backends; the trace data itself is emitted by the worker, not rendered here. Set `VITE_LANGFUSE_TRACES_URL` and `VITE_PHOENIX_URL` to a deep link to land on the traces rather than a landing page.
