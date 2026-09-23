# 06 — Offline Evaluation & Golden Datasets Page

**Last updated:** 2026-09-23

## 1. Executive Summary & Page Purpose
The **Offline Evaluation** page (`frontend/src/pages/GoldenEvaluationsPage.tsx`, route `/golden-evaluations`, nav label "Offline Evaluation") benchmarks **one pipeline configuration** against a golden question/answer dataset stored in Postgres. The operator picks a pipeline, picks how many rows to run, starts a run, and reads aggregate and per-question scores split into three stages: **retrieval**, **reranking**, **generation**.

The page was reworked on 2026-09-23 around a built-in evaluation set:

- **The set** is imported from the Hugging Face Hub once, through `POST /evaluate/datasets/huggingface`: **65** question/answer pairs drawn from the Hugging Face documentation (`m-ric/huggingface_doc_qa_eval`). It is stored as an ordinary golden dataset, so a run against it is an ordinary run and its rows appear in the dataset list.
- **Rows to test** samples N rows at random, default **5**. The sample belongs to the run, and a seed makes it reproducible.
- **The pipeline picker** fills in the pipeline's own configuration: its strategy, its Knowledge Product's store names, its embedding model and its chat model. The evaluator reads those stores, so the run measures that pipeline rather than the service defaults.

> **The set and the corpus must match.** Every question in the built-in set is answerable only from `A-Roucher/huggingface_doc`, the corpus it was generated from. A pipeline whose Knowledge Product does not hold that corpus retrieves nothing: every retrieval metric reads 0.0 and the generated answer names the file it did read instead. That measures the corpus, not the pipeline. The page states this beside the control.

The upload-a-JSON control and the Strategy / RAG Mode / Max Loops selects were removed: the offline evaluator runs `retrieve → rerank → generate` and has no router and no self-corrective loop, so those three never changed anything.

It is not the live-metrics page: `pages/EvaluationsPage.tsx` serves `/evaluations` ("Real Time Monitoring") from chat metrics. No `/evaluations/offline` or `/evaluations/golden` route exists; `App.tsx` only keeps the `/directories*` legacy redirects.

All requests go to the RAG API (`VITE_RAG_API_URL`, default `http://localhost:8001`) whose `/evaluate` router is registered in `rag_api/main.py:77`. Every route is behind the API-key dependency (`rag_api/main.py:62`); the frontend sends `X-API-Key` (`frontend/src/api.ts:13`).

---

## 2. Evaluation Metrics

Metrics are produced per stage by `eval_core`, stored per run item as `retrieval_metrics`, `rerank_metrics`, `generation_metrics` (`rag_db/models/evaluation.py:56-71`), and averaged at run level.

```
+--------------------+-----------------------------------------------------------------------+
| Stage              | Metric keys actually produced                                         |
+--------------------+-----------------------------------------------------------------------+
| 1. Retrieval       | precision, recall, hit, mrr                                           |
|    (formula-based) | Computed at k = 5; the k_values argument is accepted but not used.    |
| 2. Reranking       | mrr_before, mrr_after, mrr (= mrr_after), mrr_delta, kendall_tau,     |
|                    | ndcg (k = 5)                                                          |
| 3. Generation      | faithfulness, answer_relevancy (RAGAS); accuracy and                  |
|    (RAGAS judge)   | answer_correctness only when the item has a ground_truth_answer       |
+--------------------+-----------------------------------------------------------------------+
```

Sources: `eval_core/retrieval_metrics.py:50-60`, `eval_core/rerank_metrics.py:65-90`, `eval_core/ragas_client.py:165-241`.

- **Source matching** is name-substring based after normalization (file basename, or URL netloc + path) plus an optional exact `page` comparison: `eval_core/source_match.py:17-27, 29-57, 98-121`.
- `context_precision` / `context_recall` exist in `calculate_retrieval_ragas_async` (`ragas_client.py:117-163`) but the offline runner never calls it — `GoldenItemEvaluator.evaluate_item` only calls `compute_generation_ragas_metrics` (`eval_core/runner.py:90-95`). Offline run items therefore contain no context precision/recall values.
- Generation metrics are skipped (empty dict) when `ragas_enabled` is false, the answer is blank, there are no contexts, or the item is excluded by the skip rule `label == "incorrect"` or `category in {"out_of_corpus", "unanswerable"}` (`ragas_client.py:15-16, 107-111, 130-133, 176-186`).
- Judge model and transport: `settings.ragas_judge_model` (default `llama-3.3-70b-versatile`) through the LiteLLM proxy (`LITELLM_PROXY` / `LITELLM_BASE_URL` env, else `settings.litellm_base_url`, `/v1` appended) — `ragas_client.py:21-58`.

**Aggregate metrics** (`rag_db/repositories/evaluation_repository.py:236-282`) average every numeric key of every *completed* item and prefix it with `mean_`:

```json
{
  "retrieval":  { "mean_precision": 0.71, "mean_recall": 0.68, "mean_hit": 0.84, "mean_mrr": 0.63 },
  "reranker":   { "mean_mrr_before": 0.63, "mean_mrr_after": 0.79, "mean_mrr": 0.79,
                  "mean_mrr_delta": 0.16, "mean_kendall_tau": 0.41, "mean_ndcg": 0.81 },
  "generation": { "mean_faithfulness": 0.92, "mean_answer_relevancy": 0.88 },
  "item_count": 32,
  "config": { "retrieval_mode": "hybrid", "retrieve_limit": 20, "rerank_enabled": true, "...": "..." }
}
```

The exact key set follows what the items contain, so `mean_accuracy` / `mean_answer_correctness` appear only for items that had a ground-truth answer. The UI renders whatever numeric keys the selected stage block holds (`GoldenEvaluationsPage.tsx:176-256`).

---

## 3. Golden Dataset Format & Validation

Payload schema (`eval_core/dataset_schema.py:9-42`):

| Field | Required | Validation |
|---|---|---|
| `name` | yes | non-blank after strip; must be unique per dataset |
| `description` | no | free text |
| `items` | yes | must contain at least one entry |
| `items[].question` | yes | non-blank after strip |
| `items[].ground_truth_answer` | no | used as the RAGAS reference for accuracy / answer correctness |
| `items[].expected_sources` | no | list of strings or `{ "name": ..., "page": ... }` objects |
| `items[].metadata` | no | arbitrary object; `metadata.category` drives the RAGAS skip rule and the drill-down filter, `metadata.label` feeds the same skip rule |

Legacy aliases accepted and normalized on import (`dataset_schema.py:45-93`): `query` → `question`, `response` → `ground_truth_answer`, `source` (string, list or object) → `expected_sources`. Source entries without a usable name are dropped.

Upload rules (`rag_api/routes/evaluate.py:144-163`):

- Only `.json` uploads; anything else → `422 file must be a .json file`.
- Empty bytes → `422 uploaded file is empty`.
- Malformed or schema-violating JSON → `422 Invalid dataset JSON: <pydantic error>`.
- A dataset whose `name` already exists → `409 Dataset '<name>' already exists`, unless `?replace=true` is passed, in which case the existing dataset, its items and its runs are deleted first (`evaluation_repository.py:47-80, 113-136`).

---

## 4. Backend APIs & Contracts

| Method | Endpoint | Description | Request / Response |
|---|---|---|---|
| `POST` | `/evaluate/datasets` | Creates a golden dataset from a JSON body | `GoldenDatasetPayload` → `CreateDatasetResponse` |
| `POST` | `/evaluate/datasets/upload` | Uploads a golden dataset file (multipart `file`, query `replace`) | `CreateDatasetResponse` |
| `GET` | `/evaluate/datasets` | Lists datasets, newest first (`limit` 1–100, default 50) | `DatasetListResponse` |
| `GET` | `/evaluate/datasets/{dataset_id}` | Single dataset summary | `DatasetSummary` (404 `Dataset not found`) |
| `DELETE` | `/evaluate/datasets/{dataset_id}` | Deletes dataset, its items, and its runs/run items | `204`, or 404 |
| `GET` | `/evaluate/datasets/{dataset_id}/runs` | Lists runs for a dataset (`limit` 1–100 default 20, `skip` default 0) | `DatasetRunsResponse` |
| `POST` | `/evaluate/runs` | Enqueues an evaluation run | `CreateEvalRunRequest` → `CreateEvalRunResponse` |
| `GET` | `/evaluate/runs/{run_id}` | Polls run status, progress, aggregate metrics, error | `EvalRunResponse` (404 `Run not found`) |
| `GET` | `/evaluate/runs/{run_id}/items` | Per-item scores, answers, sources, error | `EvalRunItemsResponse` |
| `GET` | `/evaluate/stats` | Recent runs across all datasets (`limit` 1–100, default 20) | `EvaluationStatsResponse` |

`EvalRunConfig` (`evaluate.py:14-25`) — the configurable run parameters, with defaults:

| Field | Default |
|---|---|
| `retrieval_mode` | `"hybrid"` |
| `retrieve_limit` | `20` |
| `rerank_enabled` | `true` |
| `rerank_model` | `null` |
| `top_k` | `5` |
| `generation_model` | `null` |
| `k_values` | `[1, 3, 5, 10]` |
| `collection` | `null` |
| `embedding_model` | `null` |
| `sparse_embedding_model` | `null` |
| `rag_mode` | `"normal"` |
| `self_corrective_max_loops` | `3` |
| `router_enabled` | `false` |

Sample run response (`GET /evaluate/runs/{id}`, model `EvalRunResponse` at `evaluate.py:47-58`):

```json
{
  "run_id": "7fa291b8-4c31-419b-a01c-8b89d412e001",
  "dataset_id": "1c2f0f5e-8f6f-4a2f-9d7e-2f2a9d0d1a11",
  "status": "completed",
  "config": { "retrieval_mode": "hybrid", "retrieve_limit": 20, "rerank_enabled": true },
  "aggregate_metrics": { "retrieval": { "mean_mrr": 0.63 }, "item_count": 32, "config": {} },
  "error_message": null,
  "progress": { "items_total": 32, "items_completed": 32, "items_failed": 0 },
  "created_at": "2026-09-16T08:31:00.000000+00:00",
  "started_at": "2026-09-16T08:31:02.000000+00:00",
  "completed_at": "2026-09-16T08:45:00.000000+00:00"
}
```

Per-item row (`EvalRunItemResponse`, `evaluate.py:235-248`): `item_id`, `dataset_item_id`, `status`, `question`, `expected_sources`, `ground_truth_answer`, `generated_answer`, `retrieval_metrics`, `rerank_metrics`, `generation_metrics`, `category` (from `metadata.category`), `error_message`.

---

## 5. Run Lifecycle, Statuses, Progress, Error Surfacing

```
POST /evaluate/runs ──▶ run.status = "queued"   (created in DB, job pushed to RQ)
                            │
                    worker starts item loop
                            ▼
                       run.status = "running"   (mark_run_running)
                            │
        per dataset item: run item "pending" ──▶ "completed" | "failed"
                            ▼
        aggregate_run_metrics() + run.status = "completed"
                            │
              unhandled worker error ──▶ run.status = "failed"
```

- **Run statuses** are exactly `queued`, `running`, `completed`, `failed` (`rag_db/models/evaluation.py:45`; `evaluation_repository.py:146, 154-175`).
- **Item statuses** are exactly `pending`, `completed`, `failed` (`models/evaluation.py:64`; `evaluation_repository.py:196-234`).
- **Progress** (`evaluation_repository.py:177-194`): `items_total` is the dataset's item count, `items_completed` / `items_failed` are counts of run items in those statuses. A failed item never increments `items_completed`.
- **Error surfacing**: a failed run stores `aggregate_metrics = {"error": "<message>"}` and the API only exposes it as `error_message` when `status == "failed"` (`evaluate.py:361-366`). Failed items carry their own `error_message`, shown in the drill-down row.
- **Polling**: the UI re-fetches `GET /evaluate/runs/{run_id}` every 2500 ms while the run is neither `completed` nor `failed`; on completion it loads the item list once (`GoldenEvaluationsPage.tsx:480-499`).

---

## 6. Queue & Worker

- Queue name: `settings.rq_eval_queue`, default `"eval"` (`rag_shared/config.py:18`).
- The API builds one RQ `Queue` at startup with `default_timeout = settings.rq_default_timeout` (3600 s) (`rag_api/main.py:36-39, 53`).
- `POST /evaluate/runs` enqueues `eval_worker.tasks.run_evaluation` with the run id (`evaluate.py:337`).
- Worker process: `eval_worker.main.run()` initialises tracing and runs `Worker([settings.rq_eval_queue])` with `with_scheduler=False` (`apps/eval-worker/src/eval_worker/main.py`).
- `run_evaluation` (`eval_worker/tasks.py:96-252`): marks the run `running`, rebuilds a `PipelineConfig` from the stored run config, iterates the dataset items (creating a run item, invoking the evaluator, persisting the result), then aggregates and marks the run `completed`. Any exception escaping the loop marks the run `failed` and re-raises; a per-item exception is caught, written to that item as `failed`, and the loop continues.
- The same queue also carries live chat metric jobs (`eval_worker.tasks.compute_chat_metrics`), and the RAG API exposes the equivalent per-message metrics endpoint separately (`rag_api/routes/chat.py:764`).

---

## 7. UI Layout & Components

```
+-----------------------------------------------------------------------------------------------+
|  Offline Evaluation                                                                           |
|  Pick a pipeline configuration, run a random sample of the evaluation set, read the scores     |
+-----------------------------------------------------+-----------------------------------------+
|  Evaluation set            [ Refresh from HF ]      |  Run                                    |
|  != This set asks about the Hugging Face            |  Pipeline configuration                 |
|     documentation. Its questions are answerable     |  (name · strategy · knowledge product)  |
|     only from A-Roucher/huggingface_doc ...=        |  reads <store> · embedding=<model>      |
|  - HF Doc QA (65 items)                       Delete |  Rows to test [ 5 ]                     |
|                                                     |  5 of 65 rows, chosen at random         |
|                                                     |  Retrieval: dense | sparse | hybrid     |
|                                                     |  Chunk limit, Rerank checkbox           |
|                                                     |  [ Run evaluation on 5 rows ]           |
+-----------------------------------------------------+-----------------------------------------+
|  Runs (10 per page, server-side skip/limit paging)                                            |
|  Run       | Status    | Progress        | Created | Config                               |
|  ----------+-----------+-----------------+---------+-------------------------------------- |
|  7fa291b8… | completed | 32/32           | 2h ago  | hybrid · limit 20 · rerank on · ...   |
+-----------------------------------------------------------------------------------------------+
|  [ Analytics & Rubric ]  [ Drill-down (Per-question) ]                                        |
|  Overall KPIs: stage tabs Retrieval / Reranker / Generation, list or bar-chart toggle         |
|  Evaluation Rubric: Retrieval / Reranking / Generation rows with Excellent >=85%,             |
|                     Good 65-84%, Poor <65% distribution (per category filter)                 |
|  Drill-down: question, category, route badge, expected sources, P/R/MRR, delta/NDCG/tau,      |
|              Faith/Relev/Acc                                                                  |
+-----------------------------------------------------------------------------------------------+
```

Sources: `GoldenEvaluationsPage.tsx` — page size 10, the header, the evaluation-set panel, the run panel, the runs table and paging, the stage tabs and rubric table, and the drill-down table. Rubric thresholds are 0.85 / 0.65. The "Metrics by Category" panel renders only if `aggregate_metrics.categories` exists, which the aggregation code never produces.

The Strategy, Classifier, RAG Mode and Max Loops controls are gone: the offline evaluator runs `retrieve → rerank → generate` and has no router and no self-corrective loop, so they changed nothing.

---

## 8. Defects found and fixed on 2026-09-23

The page could not produce a result before this date. Every one of these fails **every** item, and the first two were already recorded in this section before the fix.

| Defect | Effect | Fix |
|---|---|---|
| `run_evaluation` passed `router_enabled=` / `router_mode=` to `evaluate_item`, which never accepted them | `TypeError` on every item | The arguments are gone, and the worker no longer computes them |
| The block read `result.latency_ms`, and `EvalItemResult` defines no such field | Failed **after** each successful evaluation, so no result was ever saved | Read through `getattr(result, "latency_ms", None) or {}` |
| The evaluator called `Retriever.retrieve` without `strategy` and `stores` | Always read the legacy scrape collection on Qdrant `:6333`, never a Knowledge Product store on `:6335` — `404 Collection doesn't exist` | `evaluate_item` takes `strategy` and `stores`; the run config carries them |
| The run carried no `generation_model` | Fell back to `settings.chat_model`, `llama-3.3-70b-versatile`, which the proxy does not serve (`400 Invalid model name`) | The page sends the pipeline's `chat_model` |
| `settings.ragas_judge_model` defaulted to `llama-3.3-70b-versatile`, also unserved | RAGAS scoring never returned, so a run stalled on its first item | `RAGAS_JUDGE_MODEL=Gpt-oss-20b` in `backend/.env` |

Still true:

- `generation_metrics` for offline items hold only RAGAS keys, so `generation_metrics.route` and `generation_metrics.sc_iterations` never exist: the drill-down Route badge falls back to the run config and the CRAG loop expansion stays inert (`GoldenEvaluationsPage.tsx:1042-1043, 1111-1120`).
- The run progress denominator is the **dataset** size, not the sample, so a 3-row sample of 65 reports `3/65`. Cosmetic, but it reads as a stalled run.
- Offline runs share the `eval` queue with per-message chat metrics on a single worker. A backlog of `compute_chat_metrics` jobs starves them; 78 pending jobs at roughly 4m40s each is about six hours. Offline runs need their own queue or more workers.
