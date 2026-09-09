# 05. Real-Time Monitoring Page (`/monitoring`)

## 1. Page Purpose & Summary

The **Real-Time Monitoring** (`/monitoring`) page provides live operational metrics, query latency telemetry, vector DB performance, and system throughput monitoring for the RAG query engine.

---

## 2. Key Metrics & Telemetry Breakdown

1. **Sub-Second Latency Waterfall**:
   - **Guardrails Pre-Check**: Latency (ms) to validate prompt safety.
   - **Vector Dense Search**: Qdrant embedding lookup duration.
   - **BM25 Sparse Search**: Sparse index search duration.
   - **Cross-Encoder Rerank**: Reranker model execution time.
   - **LLM First-Token Time (TTFT)**: Time to start streaming response.
   - **Total Generation Duration**: Total latency to complete response.
2. **Throughput Charts**: Queries Per Second (QPS), Active Streaming Connections, Error Rates (4xx/5xx).
3. **Token Usage Metrics**: Input tokens, output tokens, total cost estimation ($).

---

## 3. Data Fetching & API Interactions

- Integrates directly with OpenTelemetry traces emitted by `@trace_span` in `rag-app-workspace/libs/shared`.
- Polling Endpoint: `GET /api/rag/monitoring/metrics`
