# 12 — RAG Evaluation Metrics Reference Guide

**Last updated:** 2026-10-02

This document lists every metric the evaluation pipeline actually computes, the exact key it is stored under, how it is computed, its direction, and whether it requires an LLM judge (RAGAS) or is pure computation. It covers both **Live Chat** evaluation and **Offline (Golden Dataset)** evaluation.

Metric sources:

| Concern | File |
|---|---|
| Formula-based retrieval metrics | `backend/libs/eval-core/src/eval_core/retrieval_metrics.py` |
| Formula-based rerank metrics | `backend/libs/eval-core/src/eval_core/rerank_metrics.py` |
| Golden-source matching | `backend/libs/eval-core/src/eval_core/source_match.py` |
| RAGAS (LLM-judge) metrics | `backend/libs/eval-core/src/eval_core/ragas_client.py` (`generation_metrics.py` only re-exports these names) |
| Live-chat staging | `backend/libs/eval-core/src/eval_core/chat_metrics.py` |
| Offline per-item runner | `backend/libs/eval-core/src/eval_core/runner.py` (RAGAS metrics) and `.../eval_core/custom_metrics.py` (the two custom, non-RAGAS metrics) |
| Run aggregation | `backend/libs/database/src/rag_db/repositories/evaluation_repository.py` |
| Workers | `backend/apps/eval-worker/src/eval_worker/tasks.py` |
| Read APIs | `backend/apps/rag-api/src/rag_api/routes/chat.py`, `routes/evaluate.py` |

---

## Retrieval Metrics

### 1. Formula-based metrics (offline golden runs only)

`compute_retrieval_metrics(chunks, expected_sources, k_values)` returns exactly four keys. Precision, recall and hit use a **fixed `k = 5`**; `mrr` reads the full returned list:

| Key | Definition | Edge cases |
|---|---|---|
| `precision` | relevant chunks in the top 5 divided by the number of chunks in the top 5 | `0.0` when `k <= 0` or the top-5 slice is empty |
| `recall` | expected sources matched in the top 5 divided by the total number of expected sources | `0.0` when there are no expected sources |
| `hit` | `1.0` if any expected source appears in the top 5, else `0.0` | — |
| `mrr` | `1 / rank` of the first relevant chunk over the **full** returned list (not truncated to k) | `0.0` if no relevant chunk exists |

`k_values` is accepted as an argument and ignored by the function body; there is no per-k variant in the returned dict (no `precision_at_5`, `recall_at_3`, …). `backend/tests/unit/test_retrieval_metrics.py` still asserts `recall_at_3` / `hit_at_3`, which the current implementation does not produce.

### 2. RAGAS metrics (live chat only)

| Key | Metric class | Inputs |
|---|---|---|
| `context_precision` | `ragas.metrics.collections.ContextPrecision` | `user_input=question`, `reference`, `retrieved_contexts` |
| `context_recall` | `ragas.metrics.collections.ContextRecall` | `user_input=question`, `reference`, `retrieved_contexts` |

In live chat the contexts are the pre-rerank `retrieved_chunks` texts and the reference is the generated answer (there are no gold labels). `context_recall` is included unless the caller passes `include_context_recall=False`. No RAGAS retrieval metric is computed in the offline golden path.

---

## Source Matching (defines "relevant")

Retrieval and rerank metrics are computed on exact source matching, not on LLM judgement:

* Candidate strings taken from the chunk: `source_locator`, `title`, `metadata.file_name`, `metadata.url`, `metadata.source_locator`.
* Page number taken from the first present of `metadata.page_index` (incremented by 1), `metadata.page_number`, `metadata.page`, `metadata.page_num`, `metadata.page_label`.
* Normalization (`normalize_source`): URLs become `netloc + path` with `www.` stripped and trailing `/` trimmed; non-URL values become their basename; both sides are lowercased. Matching is bidirectional substring containment.
* A source matches when a name candidate matches **and** (if the expected entry carries a page) the chunk page equals that page. Golden entries without a page match by name alone.
* Golden sources are normalized by `parse_expected_sources` into `{name, page?}`; plain strings, `{name|source, page}` dicts, and `ExpectedSource` instances are accepted, and entries with a blank name are dropped.

---

## Reranker Metrics

`compute_rerank_metrics(before, after, expected_sources, k_values)` returns (offline runs):

| Key | Definition |
|---|---|
| `mrr_before` | `mrr` of the pre-rerank list |
| `mrr_after` | `mrr` of the post-rerank list |
| `mrr` | alias of `mrr_after` |
| `mrr_delta` | `mrr_after - mrr_before` |
| `mrr_before_at_k` | `mrr` of the pre-rerank list cut to the depth the reranker produced. This is the only pair at equal depth, so the stage reading compares it with `mrr_after` |
| `kendall_tau` | `kendall_tau_rank_correlation(before, after)`, or `None` |
| `ndcg` | `ndcg_at_k(after, expected_sources, 5)` |

* `kendall_tau_rank_correlation` compares the ordering of the chunk ids shared between the two lists (`scipy.stats.kendalltau`, with a pure-Python fallback). It returns `None` when either list is empty or fewer than two ids are shared. A value of `1.0` means the reranker left the order unchanged, `-1.0` means a full reversal — it measures reordering, not answer quality.
* `ndcg_at_k` uses binary relevance and a fixed `k = 5`: `DCG = Σ rel_i / log2(i+1)` over the reranked top 5, divided by the ideal DCG built from the relevance of the full list sorted best-first; `0.0` when the ideal DCG is 0. `k_values` is likewise ignored here.
* Live chat (`compute_chat_pipeline_metrics_async`) computes `kendall_tau` whenever both chunk lists are non-empty, and additionally `mrr` and `ndcg` only when a Jaccard token-overlap heuristic derives pseudo expected sources from the generated answer (`chat_metrics.py`); with no such pseudo sources, only `kendall_tau` is stored.

---

## Generation Metrics

All generation metrics in this section are RAGAS LLM-judge metrics and require `ragas_enabled`.

| Key | Metric class | Inputs | Notes |
|---|---|---|---|
| `faithfulness` | `Faithfulness` | `user_input=question`, `response=answer`, `retrieved_contexts` (post-rerank) | skipped when the answer is empty or there are no contexts |
| `answer_relevancy` | `AnswerRelevancy` | `user_input=question`, `response=answer` | needs RAGAS embeddings; contexts are not passed |
| `answer_correctness` | `AnswerCorrectness` | `user_input`, `response`, `reference=ground_truth` | only when a ground truth is non-empty; needs RAGAS embeddings |
| `accuracy` | same value as `answer_correctness` (both keys are written) | — | golden runs only |

`AnswerCorrectness` is imported lazily; if it is unavailable the other two metrics still return. There is no separate "Answer Relevancy vs ground truth" metric and no RAGAS retrieval metric in the golden path.

### Custom generation metrics (NOT RAGAS)

These two metrics are **not RAGAS metrics**. RAGAS does not provide them. The offline runner computes them in-process from the row's own fields, with no judge model and no `ragas_enabled` requirement. Both are merged into the item's `generation_metrics` block, next to the RAGAS keys.

| Key | Definition | Notes |
|---|---|---|
| `behavior_match` | `1.0` when the answer behaves as the row's `expected_behavior` says it should, else `0.0` | a `refuse_or_abstain` row wants an abstention. Every other row wants a real answer |
| `keypoint_coverage` | the fraction of the row's `keypoints_covered` values present in the answer | a `label=value` entry is matched on the value side. A comma-separated value needs every part |

`keypoint_coverage` is **absent**, not `0.0`, for rows whose keypoints are bare tags (`mode1;mode2`). Those rows are not measurable. An absent key stays out of the mean, so a row that was never measurable cannot drag the mean down.

Unlike the RAGAS keys, these two do not need a judge model and their values are identical across two runs that use different judges.

---

## The RAG Triad and the Stage Diagnosis

The offline runner scores three more RAGAS metrics as one group, the RAG triad. `TRIAD_METRICS` names them (`ragas_client.py:263`) and `compute_triad_metrics()` produces them (`ragas_client.py:344`).

| Key | Metric class | Inputs | Reads |
|---|---|---|---|
| `context_relevance` | `ContextRelevance` | question + contexts | the retrieval result alone |
| `response_groundedness` | `ResponseGroundedness` | answer + contexts | the answer against its evidence |
| `answer_relevancy` | `AnswerRelevancy` | question + answer | the answer against the question |

`runner.py:126` merges the three keys into the same `generation_metrics` block as the other generation metrics, so no new column and no new stage exists for them. This is why the aggregate carries `mean_context_relevance` and `mean_response_groundedness` next to the older generation means.

`diagnose()` (`eval_core/attribution.py`) reads the triad and names the stage that failed. Constants: `PASS_MARK = 0.7` (`attribution.py:27`) and `RERANK_LOSS_MARGIN = 0.05` (`attribution.py:31`). The reading order:

1. No triad score at all → `unknown`.
2. `context_relevance` below the pass mark → `retrieval`; `rerank` only when reranking ran and the reranked MRR fell below the retrieved MRR by more than the margin (`rerank_mrr + RERANK_LOSS_MARGIN < retrieval_mrr`). A run whose config sets `rerank_enabled = false` stays `retrieval`.
3. `response_groundedness` below the pass mark → `generation_grounding`.
4. `answer_relevancy` below the pass mark → `generation_relevance`.
5. A partial triad → `unknown`.
6. All three pass → `healthy`.

`GET /evaluate/runs/{id}/items` returns the three scores as the per-item `triad` field and the stage reading as `diagnosis` (`routes/evaluate.py:429,433`). Both are computed when the report is read, from the stored metrics, so the rules can change without a re-run. A key the judge did not answer for is absent, not zero.

---

## Direction Reference

| Metric | Range | Higher is better | Stage |
|---|---|---|---|
| `context_precision` | 0–1 | yes | retrieval (RAGAS) |
| `context_recall` | 0–1 | yes | retrieval (RAGAS) |
| `precision`, `recall`, `hit`, `mrr` | 0–1 | yes | retrieval (formula) |
| `mrr_before`, `mrr_after`, `mrr` | 0–1 | yes | reranker |
| `mrr_delta` | -1–1 | yes (`> 0` means reranking improved MRR) | reranker |
| `ndcg` | 0–1 | yes | reranker |
| `kendall_tau` | -1–1 | not a quality score: 1.0 = order unchanged, -1.0 = reversed | reranker |
| `faithfulness` | 0–1 | yes | generation |
| `answer_relevancy` | 0–1 | yes | generation |
| `answer_correctness`, `accuracy` | 0–1 | yes | generation |
| `context_relevance` | 0–1 | yes | triad (retrieval result) |
| `response_groundedness` | 0–1 | yes | triad (answer against evidence) |
| `behavior_match` | 0 or 1 | yes | generation (custom, not RAGAS) |
| `keypoint_coverage` | 0–1 | yes (absent when not measurable) | generation (custom, not RAGAS) |

---

## Short-Circuit Rules (as implemented)

* `settings.ragas_enabled = false` → all RAGAS calls return `{}`; live-chat staging returns empty `retrieval`/`reranker`/`generation` blocks. The two custom metrics (`behavior_match`, `keypoint_coverage`) are not RAGAS metrics, so they still compute in an offline run.
* Empty answer → retrieval RAGAS and generation RAGAS are skipped.
* No (normalized, non-blank) contexts → generation RAGAS is skipped.
* `_should_skip_precision_recall(label, category)` skips `context_precision`/`context_recall` when `label == "incorrect"` or `category` is `out_of_corpus` / `unanswerable`. It is only reachable through `calculate_retrieval_ragas_async` and `calculate_eval_metrics_async` (`ragas_client.py:134,394`); the live-chat and golden-runner paths pass no `label` and no `category`, so it does not fire there.
* Non-finite RAGAS values (`NaN`), exceptions, and `None` results are dropped rather than stored.

---

## Flow: Live Chat Evaluation

```
User sends query
       │
       ▼
RAGPipeline.chat()            # POST /chat
       │
       ├─ retrieved_chunks, reranked_chunks, latency_ms  ──► chat_pipeline_traces (DB)
       └─ final answer
       │
       ▼
eval-worker job  eval_worker.tasks.compute_chat_metrics   (enqueued when
                 ragas_enabled AND chat_metrics_async)
       │
compute_chat_pipeline_metrics_async()
       │
       ├── Retrieval RAGAS : retrieved_chunks texts, reference = generated answer
       │                     → context_precision, context_recall
       ├── Reranker        : before/after ordering
       │                     → kendall_tau (+ mrr, ndcg from the answer-overlap heuristic)
       └── Generation RAGAS: reranked_chunks texts + question + answer
                             → faithfulness, answer_relevancy
       │
       ▼
flatten_chat_metrics()  → chat_message_metrics columns
  (context_precision, context_recall, faithfulness, answer_relevancy,
   kendall_tau, mrr, ndcg) + full staged structure in raw_ragas
       │
       ▼
GET /chat/stats                              → EvaluationsPage (Real Time Monitoring)
GET /chat/messages/{message_id}/metrics      → per-message metrics panel
```

Per-loop (CRAG) metrics are **not implemented**: see the note below.

---

## Flow: Offline (Golden Dataset) Evaluation

```
Upload golden JSON or CSV   { name, items[{ query, source, response, metadata }] }
       │
       ▼
POST /evaluate/runs  →  RQ queue (eval_worker.tasks.run_evaluation)
       │
GoldenItemEvaluator.evaluate_item()  per dataset item
       │
       ├── Retrieval   : compute_retrieval_metrics(retrieved, expected, k_values)
       │                 → precision, recall, hit, mrr        (k = 5, formula only)
       ├── Rerank      : compute_rerank_metrics(retrieved, reranked, expected, k_values)
       │                 → mrr_before, mrr_after, mrr, mrr_delta, kendall_tau, ndcg
       └── Generation  : compute_generation_ragas_metrics(..., ground_truth)
                         → faithfulness, answer_relevancy, answer_correctness + accuracy
                         + triad: context_relevance, response_groundedness, answer_relevancy
                         + custom, no-judge metrics: behavior_match, keypoint_coverage
       │
       ▼
EvaluationRunItem.retrieval_metrics / rerank_metrics / generation_metrics
       │
       ▼
EvaluationRepository.aggregate_run_metrics()  → EvaluationRun.aggregate_metrics
       │                                             (+ per-category `categories` block)
       │
       ▼
GET /evaluate/datasets/{id}/runs, GET /evaluate/runs/{id}/items
       │
       ▼
GoldenEvaluationsPage → Overall KPIs / Rubric Table / Metrics by Category / drill-down
```

### Aggregated metric keys

`aggregate_run_metrics` averages, per stage, every numeric key present in the completed items' JSON blocks and prefixes it with `mean_`:

| Stage | Keys produced |
|---|---|
| `retrieval` (from `retrieval_metrics`) | `mean_precision`, `mean_recall`, `mean_hit`, `mean_mrr` |
| `reranker` (from `rerank_metrics`) | `mean_mrr_before`, `mean_mrr_after`, `mean_mrr`, `mean_mrr_delta`, `mean_mrr_before_at_k`, `mean_ndcg`, `mean_kendall_tau` |
| `generation` (from `generation_metrics`) | `mean_faithfulness`, `mean_answer_relevancy`, `mean_accuracy`, `mean_answer_correctness`, `mean_context_relevance`, `mean_response_groundedness`, `mean_behavior_match`, `mean_keypoint_coverage` |

The payload also contains `item_count` and `config` (the run configuration). Runs with no completed items return empty stage blocks. `None` values (for example `kendall_tau`) are excluded from the average rather than counted as zero. An absent `keypoint_coverage` key is likewise excluded from its mean.

### Per-category breakdown

The aggregate payload also carries a `categories` block, keyed by the row's `question_type` (falling back to `category`), each entry holding `retrieval` / `reranker` / `generation` blocks of `mean_*` values plus `item_count`. `GoldenEvaluationsPage.tsx` reads `agg.categories` for its "Metrics by Category" panel. The reason for the block: one overall mean hides a strategy that is strong on single-hop lookups and weak on multi-hop reasoning. Per-question categories stay available per run item (`metadata.category`, exposed as `EvalRunItemResponse.category`) and drive the drill-down filter.

---

## CRAG / Self-Corrective Metrics

The self-corrective loop is **not implemented**. Per-iteration metrics described in earlier revisions of this document do not exist in the current code:

* `eval_core` contains no `_iteration_metrics_async` and no code path that produces `sc_iterations`.
* The self-corrective pipeline does not exist either. `RAGPipeline` implements `retrieve`, `rerank`, `generate`, `chat` and `stream_chat` only (`libs/rag-core/src/rag_core/pipeline.py:69,91,199,270,384`), and the module `rag_core.query_router` does not exist anywhere in the tree. The streaming CRAG branch (`pipeline.stream_chat_self_corrective`) and the dead `query_router` import are gone from `POST /chat/stream`. Live-chat metrics are produced only from the non-streaming `POST /chat` path.
* The frontend still reads two fields the backend does not write. `EvaluationsPage.tsx:247` reads `metrics.generation.sc_iterations`, and `EvaluationsPage.tsx:250` and `ChatPage.tsx:1158,1168` read `latency_ms.sc_loops`. `GoldenEvaluationsPage.tsx` reads neither. Nothing in the backend writes either key, so those panels render empty. `[INFERENCE]`
* The live metrics job **works**, but it used to fail: the worker passed a seventh `sc_iterations` argument to `compute_chat_pipeline_metrics`, which accepts only `settings`, `question`, `answer`, `retrieved_chunks` and `reranked_chunks`. Every call raised `TypeError` and the row was recorded as `status="failed"` with no scores. The extra argument is gone: the call is at `apps/eval-worker/src/eval_worker/tasks.py:66-72` and the signature is at `libs/eval-core/src/eval_core/chat_metrics.py:121`.
* The golden runner reads `rag_mode` and `self_corrective_max_loops` from the run config into `PipelineConfig` (`tasks.py:148-149`), but `PipelineConfig` declares neither field (`libs/rag-core/src/rag_core/schemas.py:36`), so pydantic drops both. `GoldenItemEvaluator.evaluate_item` therefore runs retrieve → rerank → generate exactly once.
* The offline (golden) path runs. `run_evaluation` calls `evaluate_item(golden, config, k_values, strategy=…, stores=…, judge_model=…)` (`tasks.py:218-225`), which matches the signature `evaluate_item(self, item, config, k_values=None, *, strategy=None, stores=None, judge_model=None)` (`runner.py:49-58`). `EvalItemResult` carries no `latency_ms`, and the worker reads it with `getattr(result, "latency_ms", None) or {}` (`tasks.py:253`) instead of failing on it.

---

## Constants and Judge Configuration

| Item | Value | Source |
|---|---|---|
| Retrieval/rerank truncation `k` | `5` (hard-coded in both metric modules; `k_values` argument unused) | `retrieval_metrics.py`, `rerank_metrics.py` |
| `eval_default_k` setting | `5` (not read by the metric functions) | `rag_shared/config.py` |
| RRF constant | `k=60`, the default of `reciprocal_rank_fusion`; the assistant `hybrid` path calls it with no `k` and fuses the Qdrant dense list with the OpenSearch BM25 list | `libs/vector-core/src/vector_core/relational.py:140`, called from `libs/retrieval-core/src/retrieval_core/kp_retriever.py:78` |
| RAGAS judge model | `RAGAS_JUDGE_MODEL`, default `llama-3.3-70b-versatile` | `rag_shared/config.py:83`; `backend/.env.example:73` sets `Gpt-oss-120b` |
| RAGAS judge model (per run) | `EvalRunConfig.judge_model`, nullable. Empty means `settings.ragas_judge_model`. Stored in `evaluation_runs.config` | `evaluate.py`, `evaluation_repository.py` |
| RAGAS LLM endpoint | LiteLLM proxy: `LITELLM_PROXY` / `LITELLM_BASE_URL` / `settings.litellm_base_url`, normalized to `.../v1`; key from `LITELLM_API_KEY` / `OPENAI_API_KEY` / `settings.openai_api_key` | `ragas_client.py` |
| RAGAS embeddings | `settings.embedding_model`, `nvidia-embed-textonly` in the shipped `.env` (2048 dimensions) — used by `AnswerRelevancy` and `AnswerCorrectness` | `ragas_client.py`, `rag_shared/config.py`, `backend/.env.example:40-42` |

```
RAGAS_JUDGE_MODEL=Qwen3-32b                 # LLM judge for all RAGAS metrics (config default: llama-3.3-70b-versatile)
CHAT_MODEL=llama-3.3-70b-versatile          # LLM used to generate the final answer
SC_MODEL=llama-3.1-8b-instant               # CRAG judge/rewriter model — not referenced by any eval_core module
```

The RAGAS judge is configured independently of `CHAT_MODEL`, so a more capable model can score evaluations without affecting chat latency. A run can also override the judge per run with `EvalRunConfig.judge_model`. Keep the same judge across two runs if you compare their scores: the judge is what makes the comparison valid.
