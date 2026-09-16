# 06 — Offline Ragas Evaluation & Golden Datasets Page

## 1. Executive Summary & Page Purpose
The **Offline Ragas Evaluation Page** (`EvaluationsPage.tsx`, route: `/evaluations/offline` and `GoldenEvaluationsPage.tsx`, route: `/evaluations/golden`) allows engineering teams to benchmark RAG pipelines against curated Golden Question-Answer Datasets. It computes industry-standard **Ragas & DeepEval** metrics: **Faithfulness**, **Answer Relevance**, **Context Precision**, and **Context Recall** in deterministic offline batch runs.

---

## 2. Evaluation Metrics & Framework

```
+-----------------------------------------------------------------------------------------------+
|                               RAGAS OFFLINE EVALUATION MATRIX                                 |
+-----------------------------------+-----------------------------------------------------------+
| Metric                            | Definition & Mathematical Verification                     |
+-----------------------------------+-----------------------------------------------------------+
| 1. Faithfulness (Groundness)      | Measures factual consistency of generated answer against   |
|                                   | retrieved context: |Claims in Context| / |Total Claims|   |
| 2. Answer Relevancy               | Quantifies how directly the response addresses the prompt |
|                                   | without adding tangential or evasive information.         |
| 3. Context Precision              | Evaluates ranking quality: Are ground-truth relevant      |
|                                   | chunks positioned at the top of retrieved results?        |
| 4. Context Recall                 | Verifies if all reference ground-truth facts were captured|
|                                   | across the retrieved chunk set.                           |
+-----------------------------------+-----------------------------------------------------------+
```

---

## 3. UI Layout & Visual Components

```
+-----------------------------------------------------------------------------------------------+
|  Offline Evaluation & Golden Datasets                                                         |
|  Benchmark pipeline iterations against curated ground-truth datasets using Ragas metrics.     |
|  [ + Upload Golden Dataset ]  [ 🚀 Run Batch Evaluation ]                                     |
+-----------------------------------------------------------------------------------------------+
|  Selected Dataset: Enterprise Resume Search Golden Suite (50 Q&A Pairs)                      |
|  Evaluation Run History:                                                                      |
|                                                                                               |
|  Run ID   | Pipeline Config           | Faithfulness | Answer Rel | Precision | Recall | Status  |
|  ---------+---------------------------+--------------+------------+-----------+--------+-------- |
|  run-0916 | Hybrid + Cohere v3.5 (v3) | 0.962        | 0.941      | 0.915     | 0.980  | DONE    |
|  run-0915 | Dense-Only BGE-Small (v2) | 0.812        | 0.830      | 0.740     | 0.820  | DONE    |
|  run-0914 | Sparse-Only BM25 (v1)     | 0.780        | 0.750      | 0.690     | 0.710  | DONE    |
+-----------------------------------------------------------------------------------------------+
|  Run Comparison Chart:                                                                        |
|  Faithfulness:  Hybrid (0.962) > Dense (0.812) > Sparse (0.780)                               |
|  Precision:     Hybrid (0.915) > Dense (0.740) > Sparse (0.690)                               |
+-----------------------------------------------------------------------------------------------+
```

---

## 4. Backend APIs & Contracts

| Method | Endpoint | Description | Request / Response |
|---|---|---|---|
| `GET` | `/evaluate/datasets` | Lists all golden datasets | `DatasetListResponse` |
| `POST` | `/evaluate/datasets` | Creates or uploads a golden dataset | `CreateDatasetResponse` |
| `POST` | `/evaluate/runs` | Triggers offline evaluation batch job | `CreateEvalRunRequest` -> `CreateEvalRunResponse` |
| `GET` | `/evaluate/runs/{run_id}` | Polls eval run status, progress, and metric scores | `EvalRunResponse` |
| `GET` | `/evaluate/runs/{run_id}/items` | Inspects per-item score breakdowns & LLM judgements | `list[EvalItemResult]` |

### Sample Evaluation Run Response (`GET /evaluate/runs/{id}`)
```json
{
  "run_id": "7fa291b8-4c31-419b-a01c-8b89d412e001",
  "dataset_name": "Enterprise Resume Search Golden Suite",
  "status": "completed",
  "items_total": 50,
  "items_completed": 50,
  "metrics": {
    "faithfulness": 0.962,
    "answer_relevancy": 0.941,
    "context_precision": 0.915,
    "context_recall": 0.980
  },
  "completed_at": "2026-09-16T08:45:00.000Z"
}
```
