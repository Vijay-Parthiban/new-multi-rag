# 13 — Golden Dataset Evaluation Requirements

**Last updated:** 2026-09-17

Implementation contract for offline golden-dataset evaluation in `rag-retrieval-chat-manager`. Every field below is taken from `eval_core/dataset_schema.py`, `routes/evaluate.py`, `eval_core/runner.py` and the evaluation repositories.

## 1. Golden Dataset Schema & Upload

### 1.1 Payload

| Field | Type | Required | Default | Validation |
|---|---|---|---|---|
| `name` | string | yes | — | must be non-blank after `strip()`; error `name must not be empty` |
| `description` | string \| null | no | `null` | — |
| `items` | array | yes | — | must contain at least one entry; error `items must contain at least one entry` |

Item object:

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `question` | string | yes | — | non-blank after `strip()`; error `question must not be empty` |
| `ground_truth_answer` | string \| null | no | `null` | passed to RAGAS `AnswerCorrectness` when non-empty |
| `expected_sources` | array | no | `[]` | normalized downstream into `{name, page?}` objects |
| `metadata` | object | no | `{}` | free-form; this is where `category` and `label` must live |

The dataset `name` is unique in the database; re-uploading an existing name without `replace=true` fails with `409 Dataset '<name>' already exists`.

### 1.2 Accepted JSON Formats

Both the current `query`/`response`/`source` form and the legacy `question`/`ground_truth_answer`/`expected_sources` form are accepted:

```json
{
  "name": "my-eval-set",
  "description": "optional",
  "items": [
    {
      "query": "What is RAG?",
      "source": [{ "name": "document.pdf", "page": 3 }],
      "response": "RAG stands for Retrieval Augmented Generation...",
      "metadata": { "category": "Direct Answer" }
    },
    {
      "query": "What is DSA?",
      "source": ["https://geeksforgeeks.org/dsa-tutorial"],
      "response": "DSA stands for Data Structures and Algorithms...",
      "metadata": { "category": "Indirect Answer" }
    }
  ]
}
```

Field mapping and `source` normalization:

* `query` → `question`; `response` → `ground_truth_answer`.
* `source` may be a single string, a single object, or an array of strings/objects. Objects use `name` (or the alias `source`) as the locator; `page` is coerced to `int` and silently dropped when it is absent, empty, or not castable.
* Entries whose name is blank are dropped; a `source` array that normalizes to nothing yields `expected_sources: []`.
* In the legacy form (`question` present, `query` absent), `expected_sources` is passed through but a list of plain strings is still converted to `{name}` objects.
* An item-level `category` key is **not** a schema field and is not copied anywhere. Category and label must be nested under `metadata` — the runner reads `metadata.label` and `metadata.category`, and the item drill-down API returns `metadata.category` as `category`.

### 1.3 Upload & Import API

| Method | Path | Request | Response | Errors |
|---|---|---|---|---|
| `POST` | `/evaluate/datasets` | JSON body = dataset payload; query `replace` (bool, default false) | `{dataset_id, name, item_count, replaced}` | `409` duplicate name without replace; `422` schema errors |
| `POST` | `/evaluate/datasets/upload` | multipart form, field `file`; query `replace` (bool, default false) | same as above | `422 file must be a .json file`; `422 uploaded file is empty`; `422 Invalid dataset JSON: <detail>`; `409` duplicate; `422` JSON body that is not an object |
| `GET` | `/evaluate/datasets?limit=N` | `limit` 1–100, default 50 | `{limit, count, items[{dataset_id, name, description, item_count, created_at}]}` | `422 limit must be between 1 and 100` |
| `GET` | `/evaluate/datasets/{dataset_id}` | — | one dataset summary | `404 Dataset not found` |
| `DELETE` | `/evaluate/datasets/{dataset_id}` | — | `204`, no body | `404 Dataset not found` |

Uploads must end in `.json` (case-insensitive) and decode as UTF-8; the whole dataset is replaced when `replace=true` (existing dataset, its runs and run items are deleted first).

---

## 2. Evaluation Core (`eval-core`)

* **Formula-based metrics (Retrieval & Reranking)** — no LLM-as-a-judge is used for the retrieval/rerank stages. `GoldenItemEvaluator.evaluate_item` computes them directly from chunk metadata.
* **Match base**: a retrieved chunk matches a golden source when one of `source_locator`, `title`, `metadata.file_name`, `metadata.url`, `metadata.source_locator` matches the source `name` (URL normalized to netloc + path with `www.` stripped and trailing `/` trimmed; non-URL values reduced to their basename; bidirectional substring match), and — when the source carries a page — the chunk page (`metadata.page_index` + 1, else `page_number`, `page`, `page_num`, `page_label`) equals it.
* **Calculation logic** (`compute_retrieval_metrics`, fixed `k = 5`):
  * **`precision`**: relevant chunks within the top 5 divided by the number of chunks in the top 5.
  * **`recall`**: expected sources matched within the top 5 divided by the total number of expected sources.
  * **`hit`**: `1.0` when any expected source appears in the top 5, else `0.0`.
  * **`mrr`**: `1 / rank` of the first relevant chunk over the full retrieved list.
* **Reranking** (`compute_rerank_metrics`, same `k = 5` for NDCG): `mrr_before`, `mrr_after`, `mrr` (alias of `mrr_after`), `mrr_delta`, `kendall_tau` (order agreement between the pre- and post-rerank lists, `None` when fewer than two chunk ids are shared) and `ndcg`.
* **LLM metrics (Generation)** — RAGAS via the LiteLLM judge: `faithfulness` against the post-rerank contexts, `answer_relevancy` from question + answer, and — when `ground_truth_answer` is non-empty — `answer_correctness` (also stored as `accuracy`, same value).
* `k_values` is accepted by both metric functions but not used; the `self_corrective_max_loops` / `rag_mode` run settings are not applied by the runner.

---

## 3. Database Layer (`rag_db`)

* **Schema** (`rag_db/models/evaluation.py`): `GoldenDataset` (unique `name`, optional `description`), `GoldenDatasetItem` (`question`, optional `ground_truth_answer`, `expected_sources` JSONB, `metadata` JSONB), `EvaluationRun` (`dataset_id`, `status`, `config` JSONB, `aggregate_metrics` JSONB, `started_at`/`completed_at`), `EvaluationRunItem` (`run_id`, `dataset_item_id`, `status`, `retrieved_chunks`, `retrieval_metrics`, `reranked_chunks`, `rerank_metrics`, `generated_answer`, `generation_metrics`, `error_message`).
* **Aggregation (`aggregate_run_metrics`)**: averages the numeric metrics of all `completed` items per stage and stores the run `config` alongside them, plus `item_count`:
  * `retrieval`: `mean_precision`, `mean_recall`, `mean_hit`, `mean_mrr`.
  * `reranker`: `mean_mrr_before`, `mean_mrr_after`, `mean_mrr`, `mean_mrr_delta`, `mean_ndcg`, `mean_kendall_tau`.
  * `generation`: `mean_faithfulness`, `mean_answer_relevancy`, `mean_accuracy`, `mean_answer_correctness`.
  * Runs without completed items return empty stage blocks with `item_count: 0`. There is no per-category aggregation in the repository.
* **Pagination helpers**: `count_runs_for_dataset(dataset_id)` and `list_runs_for_dataset(dataset_id, skip, limit)` (newest first); `get_run_progress(run_id)` returns `items_total` (dataset size), `items_completed` and `items_failed`.
* **Item status flow**: `pending` on creation → `completed` via `save_run_item_result` or `failed` via `fail_run_item` (message stored in `error_message`); the run itself is `queued` → `running` → `completed` (with aggregates) or `failed` (with `aggregate_metrics = {"error": ...}`).

---

## 4. RAG API (`rag-api`)

| Method | Path | Request | Response |
|---|---|---|---|
| `POST` | `/evaluate/datasets` | dataset payload JSON; `?replace=` | `CreateDatasetResponse` |
| `POST` | `/evaluate/datasets/upload` | multipart `file`; `?replace=` | `CreateDatasetResponse` |
| `GET` | `/evaluate/datasets` | `?limit=` (1–100, default 50) | `{limit, count, items[]}` |
| `GET` | `/evaluate/datasets/{id}` | — | `DatasetSummary` |
| `DELETE` | `/evaluate/datasets/{id}` | — | `204` |
| `GET` | `/evaluate/datasets/{id}/runs` | `?skip=` (≥0, default 0), `?limit=` (1–100, default 20) | `{items: [EvaluationRunStatItem], count}` |
| `GET` | `/evaluate/runs/{id}/items` | — | `{run_id, count, items: [EvalRunItemResponse]}` |
| `POST` | `/evaluate/runs` | `{dataset_id, config: EvalRunConfig}` | `{run_id, status: "queued"}` |
| `GET` | `/evaluate/runs/{id}` | — | `EvalRunResponse` |
| `GET` | `/evaluate/stats` | `?limit=` (1–100, default 20) | `{limit, count, items[]}` |

Run/item response keys:

* `EvalRunResponse` / `EvaluationRunStatItem`: `run_id`, `dataset_id`, `status`, `config`, `aggregate_metrics`, `error_message` (populated from `aggregate_metrics.error` only when the run failed), `progress {items_total, items_completed, items_failed}`, `created_at`, `started_at`, `completed_at`.
* `EvalRunItemResponse`: `item_id`, `dataset_item_id`, `status`, `question`, `expected_sources`, `ground_truth_answer`, `generated_answer`, `retrieval_metrics`, `rerank_metrics`, `generation_metrics`, `category` (from `metadata.category`), `error_message`.

**Config & pipeline propagation** — `EvalRunConfig` fields and defaults:

| Field | Default |
|---|---|
| `retrieval_mode` | `"hybrid"` |
| `retrieve_limit` | `20` |
| `rerank_enabled` | `true` |
| `rerank_model` | `null` |
| `top_k` | `5` |
| `generation_model` | `null` |
| `k_values` | `[1, 3, 5, 10]` (accepted; not used by the metric functions) |
| `collection` | `null` |
| `embedding_model` | `null` |
| `sparse_embedding_model` | `null` |
| `rag_mode` | `"normal"` (`"normal"` \| `"self_corrective"`) |
| `self_corrective_max_loops` | `3` |
| `router_enabled` | `false` |

`POST /evaluate/runs` persists this config as the run's `config` JSONB and enqueues `eval_worker.tasks.run_evaluation`. Golden runs therefore retrieve with the pipeline's `collection`, `embedding_model`, `sparse_embedding_model`, `retrieve_limit`, `rerank_enabled`, `rerank_model` and `top_k`, matching the live Chat path. The frontend additionally sends `router_mode`, which is not a field of `EvalRunConfig` and is ignored. The API key is enforced globally for this app (`verify_api_key`): accepted via the `X-API-Key` header or the `api_key` query parameter, no-op when `API_KEY` is empty, and bypassed for `/health`, `/docs`, `/openapi.json`, `/redoc`.

Worker/runner drift in the current tree: `run_evaluation` calls `evaluator.evaluate_item(..., router_enabled=..., router_mode=...)` and reads `result.latency_ms`, but `GoldenItemEvaluator.evaluate_item` accepts only `(item, config, k_values)` and `EvalItemResult` has no `latency_ms` field. `[INFERENCE]` Each dataset item therefore raises and is recorded with `status="failed"` when the run is executed.

---

## 5. Frontend (`rag-retrieval-chat-manager/frontend`)

* **API client (`api.ts`)**: golden-dataset calls go through `ragFetch` (`RAG_API_URL`, default `http://localhost:8001`). `ragFetch` detects `FormData` and deletes any `Content-Type` header before the request so the browser can set the multipart boundary; `uploadGoldenDataset` appends the file as the `file` form field and only appends `?replace=true` when requested.
* **Page**: `GoldenEvaluationsPage.tsx` is mounted in `components/AppLayout.tsx` (persistent page) with the navigation item `Offline Evaluation` at `/golden-evaluations`. `App.tsx` only contains legacy `/directories*` redirects and the catch-all `AppLayout`; no route is registered there for this page.
* **Dataset panel**: lists datasets with `listGoldenDatasets()` (item counts shown), selects one on click, uploads via `uploadGoldenDataset(file, replace)`, and deletes via `deleteGoldenDataset(id)`.
* **New Run panel**: loads pipeline configurations with `listPipelines()` and, on submit, maps the selected pipeline's `qdrant_collection` → `collection`, `embedding_model` → `embedding_model`, `sparse_embedding_model` → `sparse_embedding_model`; plus retrieval mode (`dense` / `sparse` / `hybrid`), chunk limit (`retrieve_limit`), a Rerank checkbox (`rerank_enabled`), and the RAG-mode controls: Strategy `Manual Selection` / `Intelligent (Auto)`, RAG Mode (`normal` / `self_corrective`) in manual mode, Classifier (`LLM (small model)` / `Heuristic rules`) in auto mode, and Max Loops (`1`–`5`) whenever auto mode or self-corrective is selected. With Auto mode selected the page forces `rag_mode: "normal"` and sends `router_enabled: true` plus `router_mode`; there is no generation-model or `k_values` control, so the run table only shows a generation model if the config already carries one. The selected pipeline's collection/embedding/sparse values are echoed under the selector.
* **Runs list**: `listDatasetRuns(datasetId, {skip, limit})` with a fixed client page size of 10 and footer `◀` / `▶` buttons driven by the returned `count`; the run table shows each run's config summary (retrieval mode, limit, rerank state, generation model, route).
* **Results (click a run to open)**: the page keeps the runs list visible and only renders run details for the selected run. Tabs:
  * `Analytics & Rubric`: overall KPIs per stage (`aggregate_metrics.retrieval/reranker/generation`), a canvas bar chart, an "Evaluation Rubric" table that buckets per-item scores (Reranking from `rerank_metrics.ndcg`; Generation from `generation_metrics.faithfulness` / `accuracy` / `answer_relevancy`), and a "Metrics by Category" panel that reads `aggregate_metrics.categories` — a key the backend never produces, so this panel never renders.
  * `Drill-down (Per-question)`: per-item rows from `listEvaluationRunItems(runId)` with a category filter (categories discovered from the returned items) and an expandable per-item metric view.

---

## 6. Key Files

* **Chunk metadata**: `backend/libs/shared/src/rag_shared/types.py` → `RetrievedChunk` (`source_locator`, `title`, `metadata`, `chunk_index`, `retrieval_score`); `RerankedChunk` extends it with `rerank_score`.
* **Dataset schema**: `backend/libs/eval-core/src/eval_core/dataset_schema.py` → payload models, validators and format normalization.
* **Evaluation core**: `backend/libs/eval-core/src/eval_core/runner.py` (`GoldenItemEvaluator`), `source_match.py` (golden-to-chunk matching), `retrieval_metrics.py` and `rerank_metrics.py` (pure metric formulas), `ragas_client.py` (LLM-judge metrics), `chat_metrics.py` (live-chat staging).
* **Worker**: `backend/apps/eval-worker/src/eval_worker/tasks.py` → `run_evaluation` (per-item loop, persistence, aggregation).
* **Database**: `backend/libs/database/src/rag_db/models/evaluation.py`, `repositories/evaluation_repository.py`.
* **API**: `backend/apps/rag-api/src/rag_api/routes/evaluate.py`.
* **Frontend**: `frontend/src/api.ts` (`ragFetch`, golden-dataset client functions), `frontend/src/pages/GoldenEvaluationsPage.tsx`, `frontend/src/components/AppLayout.tsx` (mount + nav).
