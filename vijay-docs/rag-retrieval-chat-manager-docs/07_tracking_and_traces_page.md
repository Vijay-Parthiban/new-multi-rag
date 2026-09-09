# 07. Tracking & Execution Traces Page (`/tracking`)

## 1. Page Purpose & Summary

The **Tracking & Execution Traces** (`/tracking`) page provides end-to-end distributed tracing inspection for every RAG request processed by the platform.

---

## 2. Key UI Modules & Features

1. **Traces Table**: Log list of query execution runs featuring:
   - Trace ID & Session ID
   - User Query Summary
   - Total Execution Latency (ms)
   - Status Badge (`Success`, `Blocked by Guard`, `Failed`)
   - Timestamp.
2. **Trace Detail Drawer**: Deep-dive waterfall view breaking down child spans:
   - `span.guardrails_input`
   - `span.qdrant_dense_retrieval`
   - `span.bm25_sparse_retrieval`
   - `span.cross_encoder_rerank`
   - `span.llm_generation`
   - `span.guardrails_output`
3. **Span Metadata Inspector**: Click any span to inspect exact raw input parameters, prompt text, vector scores, and model response tokens.

---

## 3. Data Fetching & API Interactions

- **`listTraces(limit)`**: `GET /api/rag/traces?limit=100`
- **`getTraceDetail(traceId)`**: `GET /api/rag/traces/{traceId}`
