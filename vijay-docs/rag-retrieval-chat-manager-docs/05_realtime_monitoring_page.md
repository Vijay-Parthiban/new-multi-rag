# Real Time Monitoring Page

## Route
`/evaluations`

## Features
Dashboards focusing on in-flight telemetry of generations and retrieval steps. Observes the context limits, latency bounds, and token usage from LLM execution spanning retrieval and semantic reranking pipelines.

## Backend APIs Used
- `GET /api/stats`
- `GET /api/runs/{run_id}`