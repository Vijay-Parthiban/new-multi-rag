# 06 — Offline Evaluation & Golden Datasets Page

**Last updated:** 2026-09-27

## 1. Executive Summary & Page Purpose
The **Offline Evaluation** page (`frontend/src/pages/GoldenEvaluationsPage.tsx`, route `/golden-evaluations`, nav label "Offline Evaluation") benchmarks **one pipeline configuration** against a golden question/answer dataset stored in Postgres. The operator picks a pipeline, picks how many rows to run, starts a run, and reads aggregate and per-question scores split into three stages: **retrieval**, **reranking**, **generation**.

The page was reworked on 2026-09-23 around a built-in evaluation set:

- **The set** is imported from the Hugging Face Hub once, through `POST /evaluate/datasets/huggingface`: **65** question/answer pairs drawn from the Hugging Face documentation (`m-ric/huggingface_doc_qa_eval`). It is stored as an ordinary golden dataset, so a run against it is an ordinary run and its rows appear in the dataset list.
- **Rows to test** samples N rows at random, default **5**. The sample belongs to the run, and a seed makes it reproducible.
- **The pipeline picker** fills in the pipeline's own configuration: its strategy, its Knowledge Product's store names, its embedding model and its chat model. The evaluator reads those stores, so the run measures that pipeline rather than the service defaults.

> **The set and the corpus must match.** Every question in the built-in set is answerable only from `A-Roucher/huggingface_doc`, the corpus it was generated from. A pipeline whose Knowledge Product does not hold that corpus retrieves nothing: every retrieval metric reads 0.0 and the generated answer names the file it did read instead. That measures the corpus, not the pipeline. The page states this beside the control.

The dataset panel carries an upload control. It accepts a `.json` file or a `.csv` file, and an optional dataset name. The Strategy / RAG Mode / Max Loops selects were removed: the offline evaluator runs `retrieve → rerank → generate` and has no router and no self-corrective loop, so those three never changed anything.

A run can name its own judge model through the **Judge model** dropdown in the run panel. Empty means the service default. Keep the same judge for two runs you intend to compare: the judge is what makes their scores comparable.

The run aggregate also carries a **per-category breakdown**. The **Metrics by Category** panel shows one row per `question_type` (falling back to `category`). One overall mean hides a strategy that is strong on single-hop lookups and weak on multi-hop reasoning.

It is not the live-metrics page: `pages/EvaluationsPage.tsx` serves `/evaluations` ("Real Time Monitoring") from chat metrics. No `/evaluations/offline` or `/evaluations/golden` route exists; `App.tsx` only keeps the `/directories*` legacy redirects.

All requests go to the RAG API (`VITE_RAG_API_URL`, default `http://localhost:8001`) whose `/evaluate` router is registered in `rag_api/main.py:77`. Every route is behind the API-key dependency (`rag_api/main.py:62`); the frontend sends `X-API-Key` (`frontend/src/api.ts:13`).

---

## 2. Evaluation Metrics

### The RAG triad names the stage

Three scores carry the headline, because each one reads a different pair of the three inputs a
turn produces. That is what lets the numbers say *which* part of the pipeline failed instead of
only *that* it failed.

| Metric | Reads | A low score points at | Needs a reference? |
|---|---|---|---|
| `context_relevance` | question + retrieved passages | Retrieval | no |
| `response_groundedness` | answer + those passages | Generation — invented | no |
| `answer_relevancy` | answer + question | Generation — off the question | no |

**None of the three needs a ground-truth answer**, so every row scores, including the
`unanswerable` and `out_of_corpus` rows that a reference-based metric cannot cover. The
reference-based numbers (`context_precision`, `context_recall`, `answer_correctness`) still
compute when a reference exists, and sit beside the triad rather than in front of it.

Sources: `eval_core/ragas_client.py` (`TRIAD_METRICS`, `calculate_triad_async`). RAGAS 0.4.3
exposes `ContextRelevance`, `ResponseGroundedness` and `AnswerRelevancy` under
`ragas.metrics.collections`, each taking exactly the fields above.

### Attribution: reading the triad

`eval_core/attribution.py` turns the three scores into one named stage. The rules, in order:

```
context_relevance below PASS_MARK            -> retrieval, or rerank when the reranked MRR
                                                fell more than RERANK_LOSS_MARGIN below the
                                                retrieved MRR (the evidence arrived and the
                                                reranker buried it)
otherwise response_groundedness below        -> generation_grounding
otherwise answer_relevancy below             -> generation_relevance
otherwise                                    -> healthy
no score at all                              -> unknown
```

`PASS_MARK` is 0.7 and `RERANK_LOSS_MARGIN` is 0.05. Both are named constants, because they are
the entire judgement.

**A missing score is not a zero.** When one judge call fails, that metric is absent and the
reading falls through to the metrics that did answer: two scores still separate the stages, and a
fabricated zero would name a stage that never ran.

**The reading is computed when a report is read**, not stored on the row. The raw numbers are
enough to reproduce it, so the rules can change without re-running anything, and a run recorded
before the triad still gets a reading for the rows that carry the needed keys. `GET /runs/{id}`
carries the means, the per-stage counts and the dominant stage; `GET /runs/{id}/items` carries the
per-row reading with its reason and evidence.

### Every metric actually produced

Metrics are produced per stage by `eval_core`, stored per run item as `retrieval_metrics`,
`rerank_metrics`, `generation_metrics` (`rag_db/models/evaluation.py:56-71`), and averaged at run
level.

```
+--------------------+-----------------------------------------------------------------------+
| Stage              | Metric keys actually produced                                         |
+--------------------+-----------------------------------------------------------------------+
| 1. Retrieval       | precision, recall, hit, mrr                                           |
|    (formula-based) | Computed at k = 5.                                                    |
| 2. Reranking       | mrr_before, mrr_after, mrr (= mrr_after), mrr_delta, kendall_tau,     |
|                    | ndcg (k = 5)                                                          |
| 3. Generation      | context_relevance, response_groundedness, answer_relevancy (the       |
|    (RAGAS judge +  | triad, no reference needed); faithfulness; accuracy,                  |
|     custom)        | answer_correctness only when the item has a ground_truth_answer;      |
|                    | behavior_match and keypoint_coverage (custom, no judge model)         |
+--------------------+-----------------------------------------------------------------------+
```

Sources: `eval_core/retrieval_metrics.py:50-60`, `eval_core/rerank_metrics.py:65-90`,
`eval_core/ragas_client.py` (`calculate_generation_ragas_async`, `calculate_triad_async`).

- **Source matching** is name-substring based after normalization (file basename, or URL netloc + path) plus an optional exact `page` comparison: `eval_core/source_match.py:17-27, 29-57, 98-121`.
- `context_precision` / `context_recall` exist in `calculate_retrieval_ragas_async` (`ragas_client.py:117-163`) but the offline runner never calls it — `GoldenItemEvaluator.evaluate_item` only calls `compute_generation_ragas_metrics` (`eval_core/runner.py:90-140`). Offline run items therefore contain no context precision/recall values.
- Generation metrics are skipped (empty dict) when `ragas_enabled` is false, the answer is blank, or there are no contexts (`ragas_client.py`). The triad follows the same gate, since all three metrics read the answer or the contexts. The two custom metrics are not RAGAS metrics, so they still compute.
- Judge model and transport: `settings.ragas_judge_model` through the LiteLLM proxy (`LITELLM_PROXY` / `LITELLM_BASE_URL` env, else `settings.litellm_base_url`, `/v1` appended). A run can override the judge with `EvalRunConfig.judge_model`; the value is stored in the run `config`.
- **Custom generation metrics (not RAGAS)**: `behavior_match` is `1.0` when the answer behaves as the row's `expected_behavior` says it should (a `refuse_or_abstain` row wants an abstention, every other row wants a real answer). `keypoint_coverage` is the fraction of the row's `keypoints_covered` present in the answer, matched on the value side for a `label=value` entry. Rows whose keypoints are bare tags are not measurable, so the key is absent rather than `0.0`.

**Aggregate metrics** (`rag_db/repositories/evaluation_repository.py:236-282`) average every numeric key of every *completed* item and prefix it with `mean_`:

```json
{
  "retrieval":  { "mean_precision": 0.71, "mean_recall": 0.68, "mean_hit": 0.84, "mean_mrr": 0.63 },
  "reranker":   { "mean_mrr_before": 0.63, "mean_mrr_after": 0.79, "mean_mrr": 0.79,
                  "mean_mrr_delta": 0.16, "mean_kendall_tau": 0.41, "mean_ndcg": 0.81 },
  "generation": { "mean_context_relevance": 0.79, "mean_response_groundedness": 0.93,
                  "mean_answer_relevancy": 0.83, "mean_faithfulness": 0.92,
                  "mean_behavior_match": 0.95, "mean_keypoint_coverage": 0.77 },
  "categories": {
    "single_hop": { "retrieval": { "mean_recall": 0.91 }, "reranker": { "mean_ndcg": 0.88 },
                    "generation": { "mean_context_relevance": 0.88 }, "item_count": 12 },
    "multi_hop":  { "retrieval": { "mean_recall": 0.44 }, "reranker": { "mean_ndcg": 0.62 },
                    "generation": { "mean_context_relevance": 0.51 }, "item_count": 9 }
  },
  "item_count": 32,
  "config": { "retrieval_mode": "hybrid", "retrieve_limit": 20, "rerank_enabled": true, "...": "..." }
}
```

The exact key set follows what the items contain, so `mean_accuracy` / `mean_answer_correctness` appear only for items that had a ground-truth answer, and `mean_keypoint_coverage` is absent when no item is measurable. The `categories` block groups the same `mean_*` values by the row's `question_type` (falling back to `category`) and carries an `item_count` per group.

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

**CSV upload.** `/evaluate/datasets/upload` also takes a `.csv` file. The reference file is `backend/tcs_policies_golden_dataset.csv`, 22 rows. Header lookup ignores case and spaces.

| CSV column | Maps to |
|---|---|
| `question` | `question` (required. A file with no `question` column gives `422`) |
| `ground_truth_answer` | the RAGAS `reference` |
| `source_doc_id` | `expected_sources`, semicolon-separated. `N/A`, `NONE` or `-` means no source |
| `reference_context` | the gold context; a value that starts with `NONE` is absent and is dropped |
| every other column | the item `metadata` JSONB |

Every other column (`id`, `question_type`, `expected_behavior`, `keypoints_covered`, `difficulty`, `notes`) lands in `metadata`, so adding a CSV column needs no migration. A CSV has no name field, so the filename stem becomes the dataset name and `?name=` overrides it.

Upload rules (`rag_api/routes/evaluate.py:144-163`):

- `.json` or `.csv` uploads; anything else → `422 file must be a .json or .csv file`.
- Empty bytes → `422 uploaded file is empty`.
- Malformed or schema-violating JSON → `422 Invalid dataset JSON: <pydantic error>`.
- A CSV with no `question` column → `422`.
- A dataset whose `name` already exists → `409 Dataset '<name>' already exists`, unless `?replace=true` is passed, in which case the existing dataset, its items and its runs are deleted first (`evaluation_repository.py:47-80, 113-136`).

---

## 4. Backend APIs & Contracts

| Method | Endpoint | Description | Request / Response |
|---|---|---|---|
| `POST` | `/evaluate/datasets` | Creates a golden dataset from a JSON body | `GoldenDatasetPayload` → `CreateDatasetResponse` |
| `POST` | `/evaluate/datasets/upload` | Uploads a golden dataset file (multipart `file`, query `replace`, `name`) | `CreateDatasetResponse` |
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
| `judge_model` | `null` — RAGAS judge for this run. Empty uses `settings.ragas_judge_model` |
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
  "aggregate_metrics": { "retrieval": { "mean_mrr": 0.63 }, "item_count": 32,
                         "categories": { "single_hop": { "retrieval": { "mean_mrr": 0.71 }, "item_count": 12 } },
                         "config": {} },
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
|  [ Upload dataset ]   (.json or .csv)              |  Judge model [ default ]                 |
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
|  Metrics by Category: one row per question_type, stage means + item_count                     |
|                                                                                               |
|  RAG TRIAD: three bars — context relevance, groundedness, answer relevance                    |
|             "13 of 19 scored rows pass. The weakest stage is Generation — off the question,    |
|              which owns 4 of the failing rows."                                               |
|             stage chips: Sound 13 · Generation — off the question 4 · Not scored 2            |
|  [ Open full run details ]  -> /golden-evaluations/runs/<run_id>                              |
+-----------------------------------------------------------------------------------------------+
```

Sources: `GoldenEvaluationsPage.tsx` — page size 10, the header, the evaluation-set panel (upload
control for `.json` or `.csv`), the run panel (including the judge-model dropdown), the runs table
and paging, the triad panel, the detail link, the rubric table and the "Metrics by Category" panel.
Rubric thresholds are 0.85 / 0.65.

**The triad panel** (`components/TriadPanel.tsx`) draws the three scores with a bar each, the
threshold colouring (>=0.70 pass, 0.50-0.70 warn, below that fail), the run's reading sentence, and
one chip per stage that has rows. It shows `not scored` for a metric the judge did not answer, which
is deliberately different from `0.000`.

**The run detail page** (`pages/EvalRunDetailPage.tsx`) serves `/golden-evaluations/runs/:runId`.
It carries the run's configuration and timing, the same triad panel, and one expandable row per
question. A row shows its own three scores, its stage badge with the reason, and, when opened, the
answer beside the expected answer and both chunk lists: what the retriever returned and what
survived the reranker. Seeing the two lists side by side is what makes a reranker fault visible,
because the passage the answer needed is in the first list and not the second. A checkbox filters to
the rows that have a problem.

**Live view.** While a selected run is `queued` or `running` the page polls every 2.5 s and rebuilds
both the run response and the row list, so the triad, the stage chips and the row count fill in as
the worker writes each row. The detail page polls on the same interval. The timer stops as soon as
the run reads `completed` or `failed`.

The Strategy, Classifier, RAG Mode and Max Loops controls are gone: the offline evaluator runs `retrieve → rerank → generate` and has no router and no self-corrective loop, so they changed nothing.

### What the 2026-09-28 refactor moved

| Before | After |
|---|---|
| `Analytics & Rubric` and `Drill-down (Per-question)` tabs | The drill-down is its own page; the tabs are gone |
| Stage means with no stage named | The triad, then a named failing stage with its reason |
| Per-question table with P/R/MRR, delta/NDCG/tau, Faith/Relev/Acc | Per-question triad, stage badge, and both chunk lists |
| Rows loaded only when a run finished | Rows and the reading refresh live while it runs |
| `GoldenEvaluationsPage.tsx` 1331 lines | 1103 lines, plus `TriadPanel.tsx` and `EvalRunDetailPage.tsx` |

---

## 9. A run whose retrieval and reranking blocks are all zero

**Symptom.** Overall KPIs shows `0` for every retrieval and reranking number, and Metrics by
Category shows `hit=0 recall=0 mrr=0` per category — while the generation block scores
normally.

**Cause: the golden dataset's `source_doc_id` values do not name the ingested files.** Nothing
errors. The matcher compares each value against the chunk's file name, finds no match, and the
metrics are computed from zero relevant chunks, which is a legitimate `0.0`.

This happened on 2026-09-29. The dataset carried shorthand:

```
WB_p4    CSR_p5;CSR_p6    WB_p1;CSR_p1;CSR_p7
```

The corpus holds `TCS-Global-Whistle-Blower-Policy.pdf` and
`TCS-Global-Policy-Corporate-Social-Responsibility.pdf`. `CSR` and `WB` appear nowhere in the
corpus, so no rule could match them — the shorthand only makes sense to the person who wrote
it. Both blocks read zero on every run of that dataset.

**Two things were wrong, and both needed fixing:**

| Fault | Fix |
|---|---|
| A CSV could not express a page at all, so `CSR_p5` was compared as the literal name `csr_p5` | `parse_expected_sources` splits a trailing `_p<digits>` into `{name, page}` |
| The dataset's names did not match the corpus | Its `source_doc_id` column now names the ingested files |

Debug `print()` calls also sat in `matches_expected_source`, one per chunk per expected source.
They are now a single `logger.debug`.

**How to tell this apart from a stale worker.** Both make the same block read zero, so check both:

```bash
# 1. Do the dataset's source names exist in the corpus?
docker exec rag-ingestion-manager-qdrant-1 sh -c \
  'curl -s -H "api-key: qdrant" -X POST http://localhost:6333/collections/<collection>/points/scroll \
   -H "Content-Type: application/json" -d "{\"limit\":100,\"with_payload\":[\"file_name\"]}"' \
  | grep -o '"file_name":"[^"]*"' | sort -u

# 2. Is the worker running the current code?
docker image inspect backend-eval-worker:latest --format '{{.Created}}'
```

If the names are absent from that list, the dataset is at fault. If they are present and the
block is still zero, the worker is running older code — see `two_project_run.md`, section 5b.

`kendall_tau` is the tell that separates the two stages: it needs no expected source, so **it
stays non-zero while `mrr`, `ndcg` and `recall` are zero.** A reranker that genuinely scored
nothing would report `kendall_tau` as `None` instead.

## 10. Defects found and fixed on 2026-09-23

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
