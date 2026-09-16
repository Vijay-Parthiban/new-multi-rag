# Tracking & Traces Page

## Route
`/tracking`

## Component
`TrackingPage.tsx`

## Features

Distributed trace viewer for RAG pipeline executions powered by OpenTelemetry.

- **Trace List**: All pipeline execution spans collected via OTel collector (port 4317 gRPC / 4318 HTTP).
- **Span Detail**: Drill into individual spans showing retrieval latency, LLM call duration, reranker time, and guardrail check time.
- **Langfuse Integration**: Traces optionally forwarded to Langfuse cloud project (`VITE_LANGFUSE_TRACES_URL` env var).

## OTel Collector Config

Defined in `otel/otel-collector-config.yaml`. Receives spans from rag-api (`OTEL_SERVICE_NAME=rag-api`) and eval-worker (`OTEL_SERVICE_NAME=eval-worker`).
