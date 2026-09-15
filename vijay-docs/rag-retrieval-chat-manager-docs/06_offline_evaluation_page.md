# Offline Evaluation (Golden Dataset) Page

## Route
`/golden-evaluations`

## Features
A crucial UI for RAG metrics (faithfulness, relevancy). Supports regression testing chunks and queries against strict expected answers (Golden Datasets). Run parallel background evaluation jobs via the decoupled `eval-worker`.

## Backend APIs Used
- `POST /api/datasets/upload`
- `GET /api/datasets/{dataset_id}/runs`
- `POST /api/runs`