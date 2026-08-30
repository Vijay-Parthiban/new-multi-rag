# Page Documentation: Offline Evaluation & Golden Dataset Benchmarking (`GoldenEvaluationsPage.tsx`)

## 1. Overview & Purpose

The **Offline Evaluation & Golden Dataset Benchmarking Page** (`/golden-evaluations`) provides regression testing and offline quality evaluation for RAG pipelines. Users can upload ground-truth golden datasets (CSV/JSON), trigger asynchronous batch evaluation jobs across vector pipeline variants, and visualize comparative benchmark scores using interactive canvas charts.

---

## 2. Page Architecture & Visual Layout

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Header: Offline Evaluation & Golden Benchmarks | [+ Upload Golden Dataset]   │
├──────────────────────────────┬──────────────────────────────────────────────┤
│ Datasets & Run History       │ Active Evaluation Benchmark Results          │
│ ┌──────────────────────────┐ │ 📊 Run #104: Production Pipeline vs Golden   │
│ │ 📁 Golden Datasets:      │ │ Dataset: Enterprise Q&A v2 (50 test pairs)  │
│ │  - Q3 Financial QA (50) │ │ Status: ● COMPLETED (18.4 sec)              │
│ │  - Arch Specs (120)      │ │ ┌──────────────────────────────────────────┐ │
│ │  - Support FAQs (80)     │ │ │ Stage KPIs:                              │ │
│ │ ├────────────────────────┤ │ │  Retrieval: MRR 0.94 | Hit@5 0.98        │ │
│ │ ⚡ Run Batch Evaluation: │ │ │  Rerank:    NDCG 0.92 | Precision 0.90   │ │
│ │  Select Dataset:         │ │ │  Gen:       Faithfulness 0.96          │ │
│ │  [ Q3 Financial QA ▾ ]   │ │ └──────────────────────────────────────────┘ │
│ │  Select Pipeline Target: │ │ 📊 Canvas Bar Chart:                         │ │
│ │  [ Hybrid RAG Index ▾ ]  │ │  [███ 0.94]  [███ 0.98]  [███ 0.92]  [███ 0.96]│ │
│ │  [🚀 Execute Batch Run]  │ │   MRR        Hit@5      NDCG       Faith     │ │
│ └──────────────────────────┘ └──────────────────────────────────────────────┘
├─────────────────────────────────────────────────────────────────────────────┤
│ Granular Question Item Results Table:                                       │
│ ┌── ID ──┬── Question ──────────────┬── Retrieval ──┬── Faithfulness ──┬── Status ┐│
│ │ q-01   │ What is 2026 ARR goal?   │ 1.00 (Hit)    │ 0.98             │ ● PASS   │
│ │ q-02   │ Where is MinIO deployed? │ 0.85 (Hit)    │ 0.92             │ ● PASS   │
│ └────────┴──────────────────────────┴───────────────┴──────────────────┴──────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Golden Dataset Schema & Benchmark Metrics

### 3.1 Golden Dataset JSON / CSV Format
Golden datasets contain curated query/ground-truth pairs used to test pipeline accuracy:
```json
[
  {
    "question": "What is the targeted ARR growth for FY2026?",
    "ground_truth": "The ARR growth target for FY2026 is 24% according to the annual report.",
    "expected_sources": [
      "annual_report_2026.pdf",
      "financial_summary.pdf"
    ]
  }
]
```

### 3.2 Evaluation Benchmark Metrics
- **Mean Reciprocal Rank (MRR)**: Evaluates rank position of the first relevant chunk in vector search.
- **Hit Rate @ K**: Percentage of queries where at least one expected context chunk was retrieved within Top-K.
- **Normalized Discounted Cumulative Gain (NDCG)**: Measures rank-weighted retrieval relevance.
- **Mean Faithfulness**: Ragas metric verifying answer alignment with context.
- **Answer Correctness**: DeepEval metric comparing generated response against ground-truth string similarity and semantic equivalence.

---

## 4. API Schemas & Request Contracts

### 4.1 `GET /api/v1/golden-datasets`
- **Description**: Returns all uploaded golden benchmark datasets.

### 4.2 `POST /api/v1/golden-datasets/upload`
- **Content-Type**: `multipart/form-data`
- **Form Fields**: `file` (JSON/CSV), `name` (Dataset Title).

### 4.3 `POST /api/v1/evaluations/run`
- **Description**: Triggers an asynchronous batch evaluation job.
- **Request Body**:
```json
{
  "dataset_id": "ds-9901-ab42",
  "pipeline_id": "pipe-001",
  "evaluators": ["ragas", "deepeval"]
}
```
- **Response**:
```json
{
  "run_id": "run-eval-8802",
  "status": "queued",
  "total_items": 50,
  "created_at": "2026-08-30T10:15:00Z"
}
```

### 4.4 `GET /api/v1/evaluations/runs/:id` & `GET /api/v1/evaluations/runs/:id/items`
- **Description**: Fetches execution status, aggregate KPIs, and per-item scores.

---

## 5. How to Run & Test

1. **Open Golden Evaluations View**: Navigate to `http://localhost:5173/golden-evaluations`.
2. **Upload Golden Dataset**:
   - Click `+ Upload Golden Dataset`.
   - Attach a sample `.json` file containing question/ground_truth pairs.
   - Enter dataset name (e.g. `Q3 Financial Benchmark`).
   - Click `Upload`.
3. **Execute Batch Evaluation Run**:
   - Select the newly uploaded dataset.
   - Choose target vector pipeline (e.g. `Hybrid Vector Pipeline`).
   - Click `Execute Batch Run`.
4. **Monitor & Inspect Canvas Charts**:
   - Observe live status update from `queued` -> `processing` -> `completed`.
   - Inspect MRR, Hit Rate, and Faithfulness bars on the interactive canvas chart.
   - Review per-item query comparisons in the granular item results table.
