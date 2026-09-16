# Real Time Monitoring Page

## Route
`/evaluations`

## Component
`EvaluationsPage.tsx`

## Features

Live monitoring of active RAG pipeline evaluation runs.

- **Active Runs Table**: Lists in-progress and recently completed evaluation runs with status, dataset name, and metric scores.
- **RAGAS Metrics**: Faithfulness, answer relevancy, context precision, context recall displayed per run.
- **Run Trigger**: Launch a new evaluation run against a dataset from the UI.

## Backend APIs Used

- `GET /api/evaluate/runs`
- `POST /api/evaluate/runs`
- `GET /api/evaluate/runs/{run_id}`
