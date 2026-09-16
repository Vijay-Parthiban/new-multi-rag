# Offline Evaluation Page

## Route
`/golden-evaluations`

## Component
`GoldenEvaluationsPage.tsx`

## Features

Batch evaluation against golden datasets for regression testing and benchmarking.

- **Dataset Management**: Upload or create golden QA datasets (question + expected answer pairs).
- **Batch Run**: Execute the full RAG pipeline against every row in the dataset.
- **Score Summary**: Aggregated RAGAS scores across the dataset with per-question breakdown.

## Backend APIs Used

- `POST /api/evaluate/datasets`
- `POST /api/evaluate/datasets/upload`
- `GET /api/evaluate/datasets`
- `GET /api/evaluate/datasets/{dataset_id}`
- `DELETE /api/evaluate/datasets/{dataset_id}`
- `GET /api/evaluate/datasets/{dataset_id}/runs`
