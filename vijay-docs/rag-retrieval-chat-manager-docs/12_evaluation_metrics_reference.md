# 12 — RAG Evaluation Metrics Reference Guide

**Last updated:** 2026-09-17

This document lists every metric the evaluation pipeline actually computes, the exact key it is stored under, how it is computed, its direction, and whether it requires an LLM judge (RAGAS) or is pure computation. It covers both **Live Chat** evaluation and **Offline (Golden Dataset)** evaluation.

Metric sources:

| Concern | File |
|---|---|
| Formula-based retrieval metrics | `backend/libs/eval-core/src/eval_core/retrieval_metrics.py` |
| Formula-based rerank metrics | `backend/libs/eval-core/src/eval_core/rerank_metrics.py` |
| Golden-source matching | `backend/libs/eval-core/src/eval_core/source_match.py` |
| RAGAS (LLM-judge) metrics | `backend/libs/eval-core/src/eval_core/ragas_client.py` (`generation_metrics.py` only re-exports these names) |
| Live-chat staging | `backend/libs/eval-core/src/eval_core/chat_metrics.py` |
| Offline per-item runner | `backend/libs/eval-core/src/eval_core/runner.py` |
| Run aggregation | `backend/libs/database/src/rag_db/repositories/evaluation_repository.py` |
| Workers | `backend/apps/eval-worker/src/eval_worker/tasks.py` |
| Read APIs | `backend/apps/rag-api/src/rag_api/routes/chat.py`, `routes/evaluate.py` |

---

## Retrieval Metrics

### 1. Formula-based metrics (offline golden runs only)

`compute_retrieval_metrics(chunks, expected_sources, k_values)` returns exactly four keys, all computed at a **fixed `k = 5`**:

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
| `kendall_tau` | `kendall_tau_rank_correlation(before, after)`, or `None` |
| `ndcg` | `ndcg_at_k(after, expected_sources, 5)` |

* `kendall_tau_rank_correlation` compares the ordering of the chunk ids shared between the two lists (`scipy.stats.kendalltau`, with a pure-Python fallback). It returns `None` when either list is empty or fewer than two ids are shared. A value of `1.0` means the reranker left the order unchanged, `-1.0` means a full reversal — it measures reordering, not answer quality.
* `ndcg_at_k` uses binary relevance and a fixed `k = 5`: `DCG = Σ rel_i / log2(i+1)` over the reranked top 5, divided by the ideal DCG built from the relevance of the full list sorted best-first; `0.0` when the ideal DCG is 0. `k_values` is likewise ignored here.
* Live chat (`compute_chat_pipeline_metrics_async`) computes `kendall_tau` whenever both chunk lists are non-empty, and additionally `mrr` and `ndcg` only when a Jaccard token-overlap heuristic derives pseudo expected sources from the generated answer (`chat_metrics.py`); with no such pseudo sources, only `kendall_tau` is stored.

---

## Generation Metrics

All generation metrics are RAGAS LLM-judge metrics and require `ragas_enabled`.

| Key | Metric class | Inputs | Notes |
|---|---|---|---|
| `faithfulness` | `Faithfulness` | `user_input=question`, `response=answer`, `retrieved_contexts` (post-rerank) | skipped when the answer is empty or there are no contexts |
| `answer_relevancy` | `AnswerRelevancy` | `user_input=question`, `response=answer` | needs RAGAS embeddings; contexts are not passed |
| `answer_correctness` | `AnswerCorrectness` | `user_input`, `response`, `reference=ground_truth` | only when a ground truth is non-empty; needs RAGAS embeddings |
| `accuracy` | same value as `answer_correctness` (both keys are written) | — | golden runs only |

`AnswerCorrectness` is imported lazily; if it is unavailable the other two metrics still return. There is no separate "Answer Relevancy vs ground truth" metric and no RAGAS retrieval metric in the golden path.

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

---

## Short-Circuit Rules (as implemented)

* `settings.ragas_enabled = false` → all RAGAS calls return `{}`; live-chat staging returns empty `retrieval`/`reranker`/`generation` blocks.
* Empty answer → retrieval RAGAS and generation RAGAS are skipped.
* No (normalized, non-blank) contexts → generation RAGAS is skipped.
* `_should_skip_precision_recall(label, category)` skips `context_precision`/`context_recall` when `label == "incorrect"` or `category` is `out_of_corpus` / `unanswerable`. It is only reachable through `calculate_eval_metrics_async` / `compute_generation_metrics`; the live-chat and golden-runner paths do not pass `label`/`category`, so it does not fire there.
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
Upload golden JSON   { name, items[{ query, source, response, metadata }] }
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
       │
       ▼
EvaluationRunItem.retrieval_metrics / rerank_metrics / generation_metrics
       │
       ▼
EvaluationRepository.aggregate_run_metrics()  → EvaluationRun.aggregate_metrics
       │
       ▼
GET /evaluate/datasets/{id}/runs, GET /evaluate/runs/{id}/items
       │
       ▼
GoldenEvaluationsPage → Overall KPIs / Rubric Table / per-question drill-down
```

### Aggregated metric keys

`aggregate_run_metrics` averages, per stage, every numeric key present in the completed items' JSON blocks and prefixes it with `mean_`:

| Stage | Keys produced |
|---|---|
| `retrieval` (from `retrieval_metrics`) | `mean_precision`, `mean_recall`, `mean_hit`, `mean_mrr` |
| `reranker` (from `rerank_metrics`) | `mean_mrr_before`, `mean_mrr_after`, `mean_mrr`, `mean_mrr_delta`, `mean_ndcg`, `mean_kendall_tau` |
| `generation` (from `generation_metrics`) | `mean_faithfulness`, `mean_answer_relevancy`, `mean_accuracy`, `mean_answer_correctness` |

The payload also contains `item_count` and `config` (the run configuration). Runs with no completed items return empty stage blocks. `None` values (for example `kendall_tau`) are excluded from the average rather than counted as zero.

There is **no `categories` key** in the aggregate payload; `GoldenEvaluationsPage.tsx` reads `agg.categories`, so its "Metrics by Category" panel never renders. Per-question categories are available per run item (`metadata.category`, exposed as `EvalRunItemResponse.category`) and are used for the drill-down filter.

---

## CRAG / Self-Corrective Metrics

Per-iteration metrics described in earlier revisions of this document are **not implemented in the current code**:

* `eval_core` contains no `_iteration_metrics_async` and no code path that produces `sc_iterations`.
* The self-corrective pipeline does not exist either: `RAGPipeline` implements only `retrieve`, `rerank`, `generate` and `chat`, and `rag_core.query_router` (imported by `POST /chat/stream`) is missing, so the streaming CRAG branch (`pipeline.stream_chat_self_corrective`) cannot run. Live-chat metrics are therefore produced only from the non-streaming `POST /chat` path.
* The frontend reads `metrics.generation.sc_iterations` (ChatPage, EvaluationsPage, GoldenEvaluationsPage) and `latency_ms.sc_loops` (ChatPage), but nothing in the backend writes either key. `[INFERENCE]` Those panels therefore render empty.
* `eval_worker/tasks.py` still calls `compute_chat_pipeline_metrics(..., sc_iterations=...)`, but `compute_chat_pipeline_metrics` / `compute_chat_pipeline_metrics_async` do not accept that keyword. `[INFERENCE]` The live metrics job therefore fails with a `TypeError` and records `status="failed"` with an error message on the message metrics row.
* The golden runner applies neither `rag_mode` nor `self_corrective_max_loops` even though both are part of `EvalRunConfig`; `GoldenItemEvaluator.evaluate_item` runs retrieve → rerank → generate exactly once, and `PipelineConfig` does not define those fields at all (they are dropped when the worker builds the config).
* The same worker/runner drift affects the offline path: `run_evaluation` calls `evaluator.evaluate_item(..., router_enabled=..., router_mode=...)` and then reads `result.latency_ms`, but `evaluate_item` accepts only `(item, config, k_values)` and `EvalItemResult` has no `latency_ms` field. `[INFERENCE]` Each golden item therefore raises and is stored with `status="failed"`.

---

## Constants and Judge Configuration

| Item | Value | Source |
|---|---|---|
| Retrieval/rerank truncation `k` | `5` (hard-coded in both metric modules; `k_values` argument unused) | `retrieval_metrics.py`, `rerank_metrics.py` |
| `eval_default_k` setting | `5` (not read by the metric functions) | `rag_shared/config.py` |
| RRF / alpha fusion constant | none — the eval code reads no fusion parameter; the hybrid list is fused upstream by Qdrant `FusionQuery(fusion=Fusion.RRF)` over dense + sparse prefetches, which has no tunable constant | `shared-libs/platform-common/src/platform_common/vector/qdrant_store.py:225-242` |
| RAGAS judge model | `RAGAS_JUDGE_MODEL`, default `llama-3.3-70b-versatile` | `rag_shared/config.py`; `backend/.env.example` sets `Qwen3-32b` |
| RAGAS LLM endpoint | LiteLLM proxy: `LITELLM_PROXY` / `LITELLM_BASE_URL` / `settings.litellm_base_url`, normalized to `.../v1`; key from `LITELLM_API_KEY` / `OPENAI_API_KEY` / `settings.openai_api_key` | `ragas_client.py` |
| RAGAS embeddings | `settings.embedding_model` (`nvidia-embed-passage`) via the same client — used by `AnswerRelevancy` and `AnswerCorrectness` | `ragas_client.py`, `rag_shared/config.py` |

```
RAGAS_JUDGE_MODEL=Qwen3-32b                 # LLM judge for all RAGAS metrics (config default: llama-3.3-70b-versatile)
CHAT_MODEL=llama-3.3-70b-versatile          # LLM used to generate the final answer
SC_MODEL=llama-3.1-8b-instant               # CRAG judge/rewriter model — not referenced by any eval_core module
```

The RAGAS judge is configured independently of `CHAT_MODEL`, so a more capable model can score evaluations without affecting chat latency.
