# RAG Evaluation Metrics — Reference Guide

This document explains every metric computed by the evaluation pipeline, when it is computed, and how data flows from the RAG pipeline through to the UI for both **Live Chat** and **Offline (Golden Dataset)** evaluations.

---

## Metric Categories

### 🔍 Retrieval Metrics
Measure how well the vector search surfaced relevant chunks **before** reranking.

#### 1. Context Precision
- **Definition:** The proportion of retrieved chunks that are actually relevant to the query. It measures the signal-to-noise ratio of the retrieval process.
- **Technical Implementation:** In `chat_metrics.py` (live chat), it uses the RAGAS `ContextPrecision` metric via `calculate_retrieval_ragas_async()`. It takes the `retrieved_chunks` as contexts and the generated `answer` as the reference. For offline golden datasets (`runner.py`), it exact-matches the returned chunk `source_locator` against the golden `expected_sources`.
- **Normal RAG Usage:** Computed on the single array of retrieved chunks to assess the standalone retriever module.
- **Self-Corrective RAG Usage:** Computed iteratively inside `_iteration_metrics_async()`. It pulls the `retrieved_chunks` specifically associated with each CRAG loop's `stage` to see if query rewrites improved retrieval precision.

#### 2. Context Recall
- **Definition:** The proportion of all relevant information required to answer the query that was successfully retrieved in the top results. It measures coverage.
- **Technical Implementation:** Uses the RAGAS `ContextRecall` metric. Found in `eval_core/ragas_client.py`, it compares the `question`, `retrieved_contexts`, and the reference `answer` (or `ground_truth_answer`).
- **Normal RAG Usage:** Helps determine if `retrieve_limit` (k) is high enough to fetch the necessary facts to form a complete answer.
- **Self-Corrective RAG Usage:** Computed per-loop. In CRAG, if a loop fails relevance checks, it's often because context recall was too low; succeeding loops normally feature higher recall due to better queries.

#### 3. Precision @k & Recall @k
- **Definition:** Precision and recall explicitly calculated on a truncated subset of only the top `k` rank results (e.g., k=1, 3, 5, 10).
- **Technical Implementation:** Computed purely by `compute_retrieval_metrics()` in `eval_core/retrieval_metrics.py`. It loops over `k_values`, slicing the list up to `k`, and exact-matching against `expected_sources`.
- **Usage:** Golden dataset only.

#### 4. MRR (Mean Reciprocal Rank) & Hit Rate
- **Definition:** MRR evaluates the rank of the first relevant chunk returned. It is `1 / rank`. Hit Rate is binary (1 if a relevant chunk was found anywhere in the list, 0 otherwise).
- **Technical Implementation:** Implemented in `compute_retrieval_metrics()`. It scans the chunks for a `source_locator` that exists in `expected_sources`. It stores `mrr` and `hit` values.
- **Usage:** Golden dataset only.

---

### 🔀 Reranker Metrics
Measure how much the reranker improved the ordering of retrieved chunks.

#### 1. Kendall-τ (Tau)
- **Definition:** A measure of rank correlation. It quantifies the agreement between two rankings of the exact same set of items. τ = 1 means identical order; -1 means perfectly reversed.
- **Technical Implementation:** Computed by `kendall_tau_rank_correlation(before, after)` in `rerank_metrics.py`. It compares the ordered array of `retrieved_chunks` against the `reranked_chunks` to score how much the cross-encoder shuffled them.
- **Normal RAG Usage:** Shows the impact of the reranking step on the raw vector scores.
- **Self-Corrective RAG Usage:** Evaluated per-loop in `_iteration_metrics_async()` by comparing the `raw_retrieved` and `raw_reranked` lists stored in that specific iteration's `stage`.

#### 2. ΔMRR (Delta MRR) & NDCG
- **Definition:** ΔMRR is the difference in MRR before vs. after reranking. NDCG (Normalized Discounted Cumulative Gain) is a metric that evaluates the overall ordering quality, heavily penalizing relevant results that are buried too low.
- **Technical Implementation:** Computed in `compute_rerank_metrics()`. It calculates the `retrieval` MRR and `reranked` MRR, storing the difference as `mrr_delta`. NDCG calculates the ideal ranking score versus the actual ranking score based on `expected_sources`.
- **Usage:** Golden dataset only.

---

### ✨ Generation Metrics
Measure the quality of the LLM-generated answer relative to the retrieved context.

#### 1. Faithfulness
- **Definition:** Measures whether the generated answer can be entirely inferred directly from the retrieved context. It identifies LLM hallucinations.
- **Technical Implementation:** Computed using the RAGAS `Faithfulness` metric in `calculate_faithfulness_ragas_async()`. The `RAGAS_JUDGE_MODEL` extracts claims from the answer and verifies if each claim is present in `reranked_contexts`.
- **Normal RAG Usage:** Checks if the final generation step adhered to the provided knowledge base facts.
- **Self-Corrective RAG Usage:** Extremely critical on a per-loop basis. The loop's own `answer` and `reranked_contexts` are checked. CRAG heavily targets improving this score across iterations.

#### 2. Answer Relevancy
- **Definition:** Measures how concisely and accurately the answer addresses the specific question asked by the user, without including irrelevant tangents.
- **Technical Implementation:** Computed using the RAGAS `AnswerRelevancy` metric. The judge LLM takes the `question` and `answer` (contexts are not strictly needed here). It essentially back-translates the answer to see if it implies the original question.
- **Normal RAG Usage:** Validates that the generated answer is highly pertinent.
- **Self-Corrective RAG Usage:** Another primary driver for CRAG loops. If an answer diverges, the loop rewrites the query. 

#### 3. Answer Correctness (Golden Only)
- **Definition:** The end-to-end measure of accuracy. It measures the semantic factual overlap between the generated answer and the known true answer.
- **Technical Implementation:** Computed using the RAGAS `AnswerCorrectness` metric in `ragas_client.py`. The `RAGAS_JUDGE_MODEL` contrasts the `answer` against the `ground_truth_answer` from the golden dataset.
- **Usage:** Used only in offline golden dataset runs (`GoldenItemEvaluator`) to see if the overall RAG or CRAG pipeline pipeline succeeded in producing the correct information.

---

## Flow: Live Chat Evaluation

```
User sends query
       │
       ▼
 RAGPipeline.chat()  /  chat_self_corrective()
       │
       ├─ retrieved_chunks  ─────────────────────────┐
       ├─ reranked_chunks   ─────────────────────────┤ stored in DB trace
       ├─ sc_iterations (CRAG): each loop stores     │ (latency_ms JSON)
       │    query / answer / contexts                │
       │    retrieved_chunks / reranked_chunks  ──── ┘
       └─ final answer
       │
       ▼
  eval-worker (async, background)
       │
  compute_chat_pipeline_metrics_async()
       │
       ├── Retrieval RAGAS
       │     input : retrieved_chunks texts
       │     reference : generated answer
       │     output : context_precision, context_recall
       │
       ├── Reranker
       │     input : chunk ordering before & after rerank
       │     output : kendall_tau
       │
       ├── Generation RAGAS
       │     input : reranked_chunks texts + question + answer
       │     output : faithfulness, answer_relevancy
       │
       └── CRAG per-iteration (when rag_mode = self_corrective)
             for each loop:
               ├── Retrieval RAGAS  (retrieved_chunks of that loop)
               ├── Reranker tau     (retrieved → reranked of that loop)
               └── Generation RAGAS (reranked contexts of that loop)
       │
       ▼
  Stored in MessageMetrics.raw_ragas JSON
  {
    "retrieval":  { "context_precision": …, "context_recall": … },
    "reranker":   { "kendall_tau": … },
    "generation": { "faithfulness": …, "answer_relevancy": …,
                    "sc_iterations": [
                      { "loop": 1, "retrieval": {…}, "reranker": {…}, "generation": {…} },
                      …
                    ]}
  }
       │
       ▼
  GET /chat/stats  →  EvaluationsPage (Live Chat Metrics tab)
       └─ per-iteration panel (collapsible) in Metrics View
```

---

## Flow: Offline (Golden Dataset) Evaluation

```
Upload golden JSON
  { question, ground_truth_answer, expected_sources, category }
       │
       ▼
  POST /evaluate/runs  →  eval-worker
       │
  GoldenItemEvaluator.evaluate_item()  (per question)
       │
  Runs pipeline with same config as prod (retrieval_mode, rerank, rag_mode…)
       │
       ├── Retrieval Metrics  (exact source matching + RAGAS)
       │     input : retrieved_chunks vs expected_sources
       │     output : precision@k, recall@k, mrr, hit_rate
       │
       ├── Rerank Metrics  (exact source matching)
       │     input : post-rerank order vs expected_sources
       │     output : ΔMRR, NDCG, kendall_tau
       │
       ├── Generation Metrics  (RAGAS with ground truth)
       │     input : reranked contexts + question + answer + ground_truth_answer
       │     output : faithfulness, answer_relevancy, answer_correctness
       │
       └── CRAG per-iteration (when rag_mode = self_corrective)
             for each loop:
               ├── Retrieval Metrics  (from stored retrieved_chunks of that loop)
               ├── Rerank Metrics     (from stored reranked_chunks of that loop)
               └── Generation Metrics vs ground_truth_answer (that loop's answer)
       │
       ▼
  Stored in EvalRunItem
  {
    retrieval_metrics:  { precision: …, recall: …, mrr: …, hit: … },
    rerank_metrics:     { mrr_delta: …, ndcg: …, kendall_tau: … },
    generation_metrics: { faithfulness: …, answer_relevancy: …, answer_correctness: …,
                          sc_iterations: [
                            { "loop": 1, "retrieval": {…}, "rerank": {…}, "generation": {…} },
                            …
                          ]}
  }
       │
       ▼
  aggregate_metrics  (mean across all items, split by category)
  {
    "retrieval":  { "mean_precision": …, "mean_recall": … },
    "reranker":   { "mean_ndcg": …, "mean_kendall_tau": … },
    "generation": { "mean_faithfulness": …, "mean_answer_relevancy": … },
    "categories": { "HR Policies": { retrieval: {…}, reranker: {…}, generation: {…} }, … }
  }
       │
       ▼
  GoldenEvaluationsPage → Overall KPIs / Category KPIs / Rubric Table
       └─ Drill-down tab: per-question expandable CRAG iterations
```

---

## Out-of-Context (OOC) Items

When `category` contains "out of context" (case-insensitive):
- **Retrieval and rerank metrics are skipped** — there are no expected sources to match against
- **Only generation faithfulness** is computed — checking if the model correctly refuses to answer
- Same rule applies per-iteration in CRAG mode

---

## Scoring LLM

All RAGAS-based metrics are evaluated using **`RAGAS_JUDGE_MODEL`** (default: `llama-3.3-70b-versatile`). This model acts as the LLM judge — it reads the question, answer, and context and scores each metric. It is configured separately from `CHAT_MODEL` so you can use a more capable model for evaluation without impacting chat latency.

```
RAGAS_JUDGE_MODEL=llama-3.3-70b-versatile   # LLM judge for all RAGAS metrics
SC_MODEL=llama-3.3-70b-versatile            # LLM used inside the CRAG loop (judge + rewriter)
CHAT_MODEL=llama-3.3-70b-versatile          # LLM used to generate the final answer
```
