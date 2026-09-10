# 05. Real-Time Monitoring Page (`/evaluations`)

## 1. Page Purpose & Summary

The **Real-Time Monitoring** (`/evaluations`) page provides live operational metrics, query latency breakdown telemetry, vector DB performance, and system throughput monitoring for the RAG query engine.

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

- Integrates with OpenTelemetry traces and telemetry stats emitted during pipeline execution.
- Polling Endpoint: `GET /api/rag/evaluations/metrics` or `GET /api/rag/evaluations`
