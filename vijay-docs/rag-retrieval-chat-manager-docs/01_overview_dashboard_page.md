# 01. Retrieval & Chat Overview Page (`/`)

## 1. Page Purpose & Summary

The **Retrieval & Chat Overview Dashboard** (`/`) is the central landing page for the `rag-retrieval-chat-manager` application. It provides real-time visibility into active RAG pipeline strategies, query volume, sub-second latency trends, AI guardrails safety status, and LLM token metrics.

---

## 2. Key UI Modules & Widgets

1. **System Operational Status Header**: Health indicators for RAG Query API (Port 8001), Guardrails Service (Port 8002), and Qdrant Vector Engine (Port 6333).
2. **Key Metric Summary Cards**:
   - **Active RAG Pipelines**: Total configured vector strategies & Qdrant collections.
   - **Total Chat Sessions**: Cumulative interactive query sessions logged.
   - **Avg Retrieval Latency**: Sub-second dense/sparse vector search duration (ms).
   - **Guardrails Violations**: Count of blocked toxic or halluncinated prompts.
3. **Recent Chat Activity**: Snapshot of latest user queries, generation model used, and rerank scores.
4. **Quick Navigation Links**: Direct action cards to launch RAG Chat (`/chat`), edit Prompts (`/prompts`), or configure Guardrails (`/guard-config`).

---

## 3. Data Fetching & API Interactions

- **`GET /api/rag/pipelines`**: Retrieves list of active vector search collections.
- **`GET /api/rag/chat/sessions`**: Fetches recent query activity logs.
- **`GET /api/guardrails/config`**: Checks safety policy enforcement status.
- **`GET /health`**: Validates backend service health.
