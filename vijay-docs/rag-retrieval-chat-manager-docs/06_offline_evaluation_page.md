# 06. Offline Evaluation Page (`/golden-evaluations`)

## 1. Page Purpose & Summary

The **Offline Evaluation** (`/golden-evaluations`) page manages batch evaluation of RAG pipelines against ground-truth evaluation datasets using industry-standard Ragas and DeepEval benchmark metrics.

---

## 2. Benchmark Metrics Evaluated

1. **Faithfulness**: Measures whether the LLM answer is grounded strictly in the retrieved context (detects hallucinations).
2. **Answer Relevancy**: Evaluates how directly the generated answer addresses the user's query.
3. **Context Precision**: Evaluates whether retrieved contexts are relevant and ranked correctly.
4. **Context Recall**: Measures whether all necessary information was successfully retrieved.
5. **Kendall's Tau & MRR**: Statistical ranking accuracy metrics.

---

## 3. Key UI Modules & Features

1. **Benchmark Datasets Table**: List of ground-truth test sets containing question-answer-context triples.
2. **New Evaluation Run Modal**: Select dataset, target RAG pipeline strategy, and evaluation metrics to run.
3. **Evaluation Progress Tracker**: Live progress bar showing total items processed, pass/fail counts, and execution status.
4. **Metrics Radar & Bar Charts**: Visual comparison of pipeline scores across multiple evaluation runs.

---

## 4. API Endpoint Reference

- **`listEvaluationDatasets()`**: `GET /api/rag/evaluations/datasets` — Retrieves benchmark datasets.
- **`createEvaluationDataset(body)`**: `POST /api/rag/evaluations/datasets` — Uploads or creates benchmark test set.
- **`listEvaluationRuns()`**: `GET /api/rag/evaluations/runs` — Lists batch evaluation execution runs.
- **`triggerEvaluationRun(body)`**: `POST /api/rag/evaluations/runs` — Dispatches background evaluation task to `eval-worker` queue.
