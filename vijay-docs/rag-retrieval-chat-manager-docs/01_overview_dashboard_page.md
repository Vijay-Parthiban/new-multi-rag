# 01. Overview Dashboard Page (`/`)

## 1. Page Purpose & Summary

The **Overview Dashboard** (`/`) is the central landing screen of the `rag-retrieval-chat-manager` application. It provides real-time query performance metrics, RAG pipeline status, prompt repository summaries, guardrails safety status, and quick shortcuts to all 11 system components.

---

## 2. Key UI Modules & Widgets

1. **System Health Status Banner**: Displays live service connectivity indicators for the RAG Query API (Port 8001), Guardrails Moderation Service (Port 8002), and Ingestion Backend (Port 8007).
2. **Key Operational Metrics Summary**:
   - **Active RAG Pipelines**: Total configured vector retrieval pipelines and Qdrant collection mappings.
   - **System Prompts Registered**: Count of customizable prompt templates across `generation_core` and `rag_core`.
   - **Recent Chat Sessions**: Active user conversation threads.
   - **Guardrail Interceptions**: Total moderation safety blocks triggered.
3. **Quick Navigation Cards**: Direct shortcuts to Chat (`/chat`), Pipelines (`/pipelines`), Real Time Monitoring (`/evaluations`), Offline Evaluation (`/golden-evaluations`), and Guardrails Config (`/guardrails-config`).

---

## 3. Data Fetching & API Interactions

- **`GET /api/rag/pipelines`**: Fetches pipeline strategy configurations.
- **`GET /api/rag/chat/sessions`**: Fetches recent chat session statistics.
- **`GET /api/prompts`**: Fetches active prompt template list.
- **`GET /api/guardrails/config`**: Fetches active safety moderation rules.
- **`GET /health`**: Health check polling confirming service availability.
