# 13 — Golden Dataset Evaluation Requirements

**Last updated:** 2026-10-02

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

### 1.3 Accepted CSV Format

`POST /evaluate/datasets/upload` accepts a `.csv` file as well as `.json`. The reference file is `rag-retrieval-chat-manager/backend/tcs_policies_golden_dataset.csv` (22 rows).

Column mapping (header lookup is case-insensitive and ignores spaces):

| CSV column | Maps to | Notes |
|---|---|---|
| `question` | `question` | required. A file without this column is rejected with `422` |
| `ground_truth_answer` | `ground_truth_answer` (the RAGAS `reference`) | optional |
| `source_doc_id` | `expected_sources` | semicolon- or comma-separated list. `N/A`, `NONE` or `-` means no source |
| `reference_context` | the gold context | a value that starts with `NONE` is treated as absent and dropped |
| every other column (`id`, `question_type`, `expected_behavior`, `keypoints_covered`, `difficulty`, `notes`) | `metadata` | stored under its own key in the item `metadata` JSONB |

Because any unknown column lands in `metadata` JSONB, adding a CSV column needs **no** migration.

### The `source_doc_id` convention — read this before authoring a dataset

This column is the only reference the retrieval and reranking metrics have. **A value that
does not match an ingested file name makes every reference-based metric read zero**, with
no error: `hit`, `recall`, `precision`, `mrr` and `ndcg` all come back `0.0` while the
`generation` block still scores normally.

Three rules:

1. **Name the ingested file, not a label of your own.** The matcher compares the value
   against the chunk's `source_locator`, `title`, `metadata.file_name`, `metadata.url` and
   `metadata.source_locator`, reduced to a basename, by bidirectional substring. So
   `TCS-Global-Whistle-Blower-Policy.pdf` matches; a shorthand such as `WB` does not, and
   never can, because nothing in the corpus carries that string.
2. **A `_p<page>` suffix from a CSV does not set a page.** The suffix splits into
   `{name, page}` only for a plain-string source (`parse_expected_sources`,
   `source_match.py:36-76`). A CSV row reaches the matcher as a dict, because `_split_sources`
   (`dataset_schema.py:130-137`) emits `{"name": "<value>"}`, and the dict branch keeps the
   whole name and sets `page=None`. So `TCS-Global-Whistle-Blower-Policy.pdf_p3` matches the
   chunk whose file name is `TCS-Global-Whistle-Blower-Policy.pdf` (the suffixed name is a
   substring of it) and the page is ignored. The fix belongs in `_split_sources`, which should
   emit plain strings, or in `parse_expected_sources`, which should split a dict's `name` with
   `_PAGE_SUFFIX` too.
3. **A page, when one is set, is 1-based against `metadata.page_index`.** The JSON form can
   send `{name, page}`, and that value does apply. A chunk at `page_index: 2` is page `3`, so
   it matches `page: 3` and not `2`.

Separate multiple sources with a semicolon or a comma. `N/A`, `NONE` or `-` means no source and is
left alone.

```
Q003,procedural_howto,...,TCS-Global-Whistle-Blower-Policy.pdf_p3,...
Q019,comparative_cross_document,...,TCS-Global-Whistle-Blower-Policy.pdf_p1;TCS-Global-Policy-Corporate-Social-Responsibility.pdf_p7,...
```

**Check the column before running anything.** Each distinct value must appear in the
corpus, or the run will report a zero retrieval block:

```bash
docker exec rag-ingestion-manager-qdrant-1 sh -c \
  'curl -s -H "api-key: qdrant" -X POST http://localhost:6333/collections/<collection>/points/scroll \
   -H "Content-Type: application/json" -d "{\"limit\":100,\"with_payload\":[\"file_name\"]}"' \
  | grep -o '"file_name":"[^"]*"' | sort -u
```

Compare that list with `cut -d, -f6 file.csv`.

A CSV carries no `name` field. The upload uses the filename stem as the dataset name, and the optional `?name=` query parameter overrides it. A JSON upload uses the file's own name, and `?name=` overrides that too (`routes/evaluate.py:214-216`).

### 1.4 Upload & Import API

| Method | Path | Request | Response | Errors |
|---|---|---|---|---|
| `POST` | `/evaluate/datasets` | JSON body = dataset payload; query `replace` (bool, default false) | `{dataset_id, name, item_count, replaced}` | `409` duplicate name without replace; `422` schema errors |
| `POST` | `/evaluate/datasets/upload` | multipart form, field `file` (`.json` or `.csv`); query `replace` (bool, default false), `name` (string; overrides the dataset name for CSV and JSON alike) | same as above | `422 file must be a .csv or .json file`; `422 uploaded file is empty`; `422 Invalid dataset JSON: <detail>`; `422 Invalid dataset CSV: <detail>`; `409` duplicate; `422` JSON body that is not an object |
| `POST` | `/evaluate/datasets/huggingface` | optional JSON body `{replace: bool}` (default false) | same as above | `502 DATASET_EMPTY` when the Hub returns no usable rows |
| `GET` | `/evaluate/datasets?limit=N` | `limit` 1–100, default 50 | `{limit, count, items[{dataset_id, name, description, item_count, created_at}]}` | `422 limit must be between 1 and 100` |
| `GET` | `/evaluate/datasets/{dataset_id}` | — | one dataset summary | `404 Dataset not found` |
| `DELETE` | `/evaluate/datasets/{dataset_id}` | — | `204`, no body | `404 Dataset not found` |

The Hugging Face import reads the dataset `m-ric/huggingface_doc_qa_eval` (`HF_DATASET`, `routes/evaluate.py:226`) through the Hub rows API and stores it as the golden dataset `HF Doc QA`. The companion corpus is `A-Roucher/huggingface_doc`, so a pipeline can answer these questions only when its Knowledge Product holds that corpus.

Uploads must end in `.json` or `.csv` (case-insensitive) and decode as UTF-8; the whole dataset is replaced when `replace=true` (existing dataset, its runs and run items are deleted first).

---

## 2. Evaluation Core (`eval-core`)

* **Formula-based metrics (Retrieval & Reranking)** — no LLM-as-a-judge is used for the retrieval/rerank stages. `GoldenItemEvaluator.evaluate_item` computes them directly from chunk metadata.
* **Match base**: a retrieved chunk matches a golden source when one of `source_locator`, `title`, `metadata.file_name`, `metadata.url`, `metadata.source_locator` matches the source `name` (URL normalized to netloc + path with `www.` stripped and trailing `/` trimmed; non-URL values reduced to their basename; bidirectional substring match), and — when the source carries a page — the chunk page (`metadata.page_index` + 1, else `page_number`, `page`, `page_num`, `page_label`) equals it. A source **string** ending in `_p<digits>` is split into `{name, page}` at parse time, but a source **object** is not; the CSV path produces objects, so a page suffix on a CSV upload is ignored and matching falls back to the file name (`source_match.py:36-76`, `dataset_schema.py:130-137`). **A name that matches nothing makes every metric in this block `0.0` with no error** — see §1.3.
* **Calculation logic** (`compute_retrieval_metrics`, fixed `k = 5`):
  * **`precision`**: relevant chunks within the top 5 divided by the number of chunks in the top 5.
  * **`recall`**: expected sources matched within the top 5 divided by the total number of expected sources.
  * **`hit`**: `1.0` when any expected source appears in the top 5, else `0.0`.
  * **`mrr`**: `1 / rank` of the first relevant chunk over the full retrieved list.
* **Reranking** (`compute_rerank_metrics`, same `k = 5` for NDCG): `mrr_before`, `mrr_after`, `mrr` (alias of `mrr_after`), `mrr_delta`, `mrr_before_at_k` (the pre-rerank list cut to the reranker's depth), `kendall_tau` (order agreement between the pre- and post-rerank lists, `None` when fewer than two chunk ids are shared) and `ndcg`.
* **LLM metrics (Generation)** — RAGAS via the LiteLLM judge: `faithfulness` against the post-rerank contexts, `answer_relevancy` from question + answer, and — when `ground_truth_answer` is non-empty — `answer_correctness` (also stored as `accuracy`, same value).
* **RAG triad (Generation)** — three RAGAS scores merged into the same `generation_metrics` block by `runner.py:127`: `context_relevance` (question + contexts), `response_groundedness` (answer + contexts) and `answer_relevancy` (question + answer). `diagnose()` (`eval_core/attribution.py`) turns them into a stage reading with `PASS_MARK = 0.7` and `RERANK_LOSS_MARGIN = 0.05`. `GET /evaluate/runs/{id}/items` returns the scores as `triad` and the reading as `diagnosis`. See `12_evaluation_metrics_reference.md` for the full rules.
* **Custom metrics (Generation)** — two metrics that RAGAS does not provide, computed in-process with no judge model and merged into the same `generation_metrics` block:
  * **`behavior_match`**: `1.0` when the answer behaves as the row's `expected_behavior` says it should. A `refuse_or_abstain` row wants an abstention; every other row wants a real answer.
  * **`keypoint_coverage`**: the fraction of `keypoints_covered` present in the answer. The runner matches a `label=value` entry on the value side, and a comma-separated value needs every part. Rows whose keypoints are bare tags (`mode1;mode2`) are not measurable, so the key is **absent** rather than `0.0`. This keeps a row that was never measurable out of the mean.
* **Judge model** — `EvalRunConfig.judge_model` overrides the RAGAS judge for one run. `null` or empty means the service default `settings.ragas_judge_model`. The run stores the value in `evaluation_runs.config`. The same judge across two runs is what makes their scores comparable.
* `k_values` is accepted by both metric functions but not used; the `self_corrective_max_loops` / `rag_mode` run settings are not applied by the runner.

---

## 3. Database Layer (`rag_db`)

* **Schema** (`rag_db/models/evaluation.py`): `GoldenDataset` (unique `name`, optional `description`), `GoldenDatasetItem` (`question`, optional `ground_truth_answer`, `expected_sources` JSONB, `metadata` JSONB), `EvaluationRun` (`dataset_id`, `status`, `config` JSONB, `aggregate_metrics` JSONB, `started_at`/`completed_at`), `EvaluationRunItem` (`run_id`, `dataset_item_id`, `status`, `retrieved_chunks`, `retrieval_metrics`, `reranked_chunks`, `rerank_metrics`, `generated_answer`, `generation_metrics`, `error_message`).
* **Aggregation (`aggregate_run_metrics`)**: averages the numeric metrics of all `completed` items per stage and stores the run `config` alongside them, plus `item_count`:
  * `retrieval`: `mean_precision`, `mean_recall`, `mean_hit`, `mean_mrr`.
  * `reranker`: `mean_mrr_before`, `mean_mrr_after`, `mean_mrr`, `mean_mrr_delta`, `mean_mrr_before_at_k`, `mean_ndcg`, `mean_kendall_tau`.
  * `generation`: `mean_faithfulness`, `mean_answer_relevancy`, `mean_accuracy`, `mean_answer_correctness`, `mean_context_relevance`, `mean_response_groundedness`, `mean_behavior_match`, `mean_keypoint_coverage`.
  * Runs without completed items return empty stage blocks with `item_count: 0`.
  * **Per-category breakdown**: the payload also carries a `categories` block keyed by the row's `question_type` from `metadata` (falling back to `metadata.category`). Each entry holds its own `retrieval` / `reranker` / `generation` blocks of `mean_*` values plus `item_count`. One overall mean hides a strategy that is strong on single-hop lookups and weak on multi-hop reasoning.
* **Pagination helpers**: `count_runs_for_dataset(dataset_id)` and `list_runs_for_dataset(dataset_id, skip, limit)` (newest first); `get_run_progress(run_id)` returns `items_total` (dataset size), `items_completed` and `items_failed`.
* **Item status flow**: `pending` on creation → `completed` via `save_run_item_result` or `failed` via `fail_run_item` (message stored in `error_message`); the run itself is `queued` → `running` → `completed` (with aggregates) or `failed` (with `aggregate_metrics = {"error": ...}`).

---

## 4. RAG API (`rag-api`)

| Method | Path | Request | Response |
|---|---|---|---|
| `POST` | `/evaluate/datasets` | dataset payload JSON; `?replace=` | `CreateDatasetResponse` |
| `POST` | `/evaluate/datasets/upload` | multipart `file`; `?replace=` | `CreateDatasetResponse` |
| `POST` | `/evaluate/datasets/huggingface` | optional body `{replace}`; imports `m-ric/huggingface_doc_qa_eval` | `CreateDatasetResponse` |
| `GET` | `/evaluate/datasets` | `?limit=` (1–100, default 50) | `{limit, count, items[]}` |
| `GET` | `/evaluate/datasets/{id}` | — | `DatasetSummary` |
| `DELETE` | `/evaluate/datasets/{id}` | — | `204` |
| `GET` | `/evaluate/datasets/{id}/runs` | `?skip=` (≥0, default 0), `?limit=` (1–100, default 20) | `{items: [EvaluationRunStatItem], count}` |
| `GET` | `/evaluate/runs/{id}/items` | — | `{run_id, count, items: [EvalRunItemResponse]}` |
| `POST` | `/evaluate/runs` | `{dataset_id, config: EvalRunConfig}` | `{run_id, status: "queued"}` |
| `GET` | `/evaluate/runs/{id}` | — | `EvalRunResponse` |
| `GET` | `/evaluate/stats` | `?limit=` (1–100, default 20) | `{limit, count, items[]}` |

Run/item response keys:

* `EvalRunResponse` / `EvaluationRunStatItem`: `run_id`, `dataset_id`, `status`, `config`, `aggregate_metrics`, `error_message` (populated from `aggregate_metrics.error` only when the run failed), `progress {items_total, items_completed, items_failed}`, `created_at`, `started_at`, `completed_at`. `EvalRunResponse` also carries `diagnosis`, whose `triad` key holds the mean of each triad metric, read from the stored per-row metrics when the response is built.
* `EvalRunItemResponse`: `item_id`, `dataset_item_id`, `status`, `question`, `expected_sources`, `ground_truth_answer`, `generated_answer`, `retrieval_metrics`, `rerank_metrics`, `generation_metrics`, `category` (from `metadata.category`), `error_message`, `triad` (the three triad scores on their own), `diagnosis` (the stage the row points at), `retrieved_chunks` and `reranked_chunks` (what the retriever returned and what survived the reranker).

**Config & pipeline propagation** — `EvalRunConfig` fields and defaults:

| Field | Default |
|---|---|
| `retrieval_mode` | `"hybrid"` |
| `retrieve_limit` | `20` |
| `rerank_enabled` | `true` |
| `rerank_model` | `null` |
| `top_k` | `5` |
| `generation_model` | `null` |
| `judge_model` | `null` — the RAGAS judge for this run. Empty uses `settings.ragas_judge_model` |
| `k_values` | `[1, 3, 5, 10]` (accepted; not used by the metric functions) |
| `collection` | `null` |
| `embedding_model` | `null` |
| `sparse_embedding_model` | `null` |
| `rag_strategy` | `null` — the assistant strategy; with the store names below it makes the runner read the Knowledge Product's stores |
| `opensearch_index` | `null` |
| `pg_schema` | `null` |
| `pg_table` | `null` |
| `sample_size` | `null` — 1 to 500. A random sample of that many rows |
| `seed` | `null` — stored with the run when set |
| `rag_mode` | `"normal"` (`"normal"` \| `"self_corrective"`) |
| `self_corrective_max_loops` | `3` |
| `router_enabled` | `false` |

`POST /evaluate/runs` persists this config as the run's `config` JSONB and enqueues `eval_worker.tasks.run_evaluation`. The frontend sends `retrieval_mode`, `retrieve_limit`, `rerank_enabled`, `collection`, `embedding_model`, `sparse_embedding_model`, `rag_strategy`, `opensearch_index`, `pg_schema`, `pg_table`, `sample_size`, `generation_model` (the selected pipeline's `chat_model`) and `judge_model` (`GoldenEvaluationsPage.tsx:636-654`). It sends **no** `rerank_model`, no `top_k`, no `router_mode`, no `rag_mode` and no `seed`, so those keys keep their defaults. In particular, no `seed` means a run draws a fresh sample every time. The API key is enforced globally for this app (`verify_api_key`): accepted via the `X-API-Key` header or the `api_key` query parameter, no-op when `API_KEY` is empty, and bypassed for `/health`, `/docs`, `/openapi.json`, `/redoc`.

The runner has no router and no self-corrective loop. `run_evaluation` calls `evaluator.evaluate_item(golden, config, k_values, strategy=…, stores=…, judge_model=…)` (`tasks.py:218-225`), which matches the runner's signature, and it reads `latency_ms` with `getattr(result, "latency_ms", None) or {}` (`tasks.py:253`). Each item runs retrieve → rerank → generate once and is stored.

---

## 5. Frontend (`rag-retrieval-chat-manager/frontend`)

* **API client (`api.ts`)**: golden-dataset calls go through `ragFetch` (`RAG_API_URL`, default `http://127.0.0.1:8001`). `ragFetch` detects `FormData` and deletes any `Content-Type` header before the request so the browser can set the multipart boundary; `uploadGoldenDataset` appends the file as the `file` form field and only appends `?replace=true` when requested. The control accepts a `.json` or `.csv` file. For a CSV it can also send `?name=`.
* **Page**: `GoldenEvaluationsPage.tsx` is mounted in `components/AppLayout.tsx` (persistent page) with the navigation item `Offline Evaluation` at `/golden-evaluations`. `App.tsx` only contains legacy `/directories*` redirects and the catch-all `AppLayout`; no route is registered there for this page.
* **Dataset panel**: lists datasets with `listGoldenDatasets()` (item counts shown), selects one on click, uploads via `uploadGoldenDataset(file, replace)`, imports the built-in Hugging Face set via `importHuggingFaceDataset(true)`, and deletes via `deleteGoldenDataset(id)`. The upload control accepts `.json` and `.csv`.
* **New Run panel**: loads pipeline configurations with `listPipelines()` and, on submit, derives the run stores with `pipelineStores` (`GoldenEvaluationsPage.tsx:392-423`): it reads the selected pipeline's Knowledge Product destinations for `collection` (vector), `opensearch_index` (lexical), `pg_schema` and `pg_table` (relational), and its `text_embedding_model` and `sparse_embedding_model` for `embedding_model` and `sparse_embedding_model`. When the pipeline has no Knowledge Product, it falls back to the pipeline's own `qdrant_collection`, `embedding_model` and `sparse_embedding_model`. The controls are: a pipeline selector, retrieval mode (`dense` / `sparse` / `hybrid`), chunk limit (`retrieve_limit`), a Rerank checkbox (`rerank_enabled`), a rows-to-test number (default 5, sent as `sample_size`), and an `LLM-as-a-judge (optional)` dropdown (`judge_model`) whose first option is `Service default` and whose other options come from the same LiteLLM catalog the Pipelines page uses. The page sends no `router_mode`, no `rag_mode` and no `seed`, so each run draws a fresh sample. There is no user-facing generation-model or `k_values` control: the run sends the selected pipeline's `chat_model` as `generation_model`, and `k_values` keeps its default. The selected pipeline's collection, embedding and sparse values are echoed under the selector.
* **Runs list**: `listDatasetRuns(datasetId, {skip, limit})` with a fixed client page size of 10 and footer `◀` / `▶` buttons driven by the returned `count`; the run table shows each run's config summary (retrieval mode, limit, rerank state, generation model, route).
* **Results (click a run to open)**: the page keeps the runs list visible and only renders run details for the selected run. There are **no result tabs**. The page renders, in this order:
  * `TriadPanel`, fed by `selectedRun.diagnosis` — the triad means and the named failing stage.
  * An `Open full run details` button that routes to `/golden-evaluations/runs/:id`.
  * `OverallKpis` — a stage selector (`Retrieval` / `Reranker` / `Generation`) over `aggregate_metrics.retrieval/reranker/generation`, with a `Chart` toggle that draws the same numbers as a canvas bar chart.
  * `Metrics by Category` — one block per key of `aggregate_metrics.categories`, each with its own retrieval, reranker and generation KPIs and `item_count`.
  * `Evaluation Rubric` — a table that buckets per-item scores (Reranking from `rerank_metrics.ndcg`; Generation from `generation_metrics.faithfulness` / `accuracy` / `answer_relevancy`).
  * Per-question rows come from the run-detail route, which calls `listEvaluationRunItems(runId)` and shows each row's triad, diagnosis and retrieved passages.

---

## 6. Key Files

* **Chunk metadata**: `backend/libs/shared/src/rag_shared/types.py` → `RetrievedChunk` (`source_locator`, `title`, `metadata`, `chunk_index`, `retrieval_score`); `RerankedChunk` extends it with `rerank_score`.
* **Dataset schema**: `backend/libs/eval-core/src/eval_core/dataset_schema.py` → payload models, validators and format normalization.
* **Evaluation core**: `backend/libs/eval-core/src/eval_core/runner.py` (`GoldenItemEvaluator`), `source_match.py` (golden-to-chunk matching), `retrieval_metrics.py` and `rerank_metrics.py` (pure metric formulas), `ragas_client.py` (LLM-judge metrics), `chat_metrics.py` (live-chat staging).
* **Worker**: `backend/apps/eval-worker/src/eval_worker/tasks.py` → `run_evaluation` (per-item loop, persistence, aggregation).
* **Database**: `backend/libs/database/src/rag_db/models/evaluation.py`, `repositories/evaluation_repository.py`.
* **API**: `backend/apps/rag-api/src/rag_api/routes/evaluate.py`.
* **Frontend**: `frontend/src/api.ts` (`ragFetch`, golden-dataset client functions), `frontend/src/pages/GoldenEvaluationsPage.tsx`, `frontend/src/components/AppLayout.tsx` (mount + nav).
