# Tracking & Traces Page

## Route
`/tracking`

## Features
Provides lineage visibility into every LLM and Search event, logging API spans traversing through `retrieval-core`, `reranker-core`, to `generation-core`. Useful for debugging failed context injections and empty outputs.

## Backend APIs Used
- Underlying `search`/`traces` data feeds are actively monitored in integration with `/api/traces` (often handled natively via OTEL interceptors).