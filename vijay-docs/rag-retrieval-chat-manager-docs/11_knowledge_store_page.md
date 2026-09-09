# 11. Knowledge Store Proxy Page (`/knowledge-store`)

## 1. Page Purpose & Summary

The **Knowledge Store Proxy** (`/knowledge-store`) page in `rag-retrieval-chat-manager` provides a read-only view of the multi-sink Knowledge Profiles and destination sinks configured inside `rag-ingestion-manager`.

---

## 2. Architectural Role & Boundary

To preserve strict domain separation between document ingestion and retrieval/chat management, retrieval engineers can view existing Knowledge Store profiles and target Qdrant collection mappings without mutating ingestion settings.

- **Vite Proxy Path**: `/api/knowledge/profiles` -> `http://localhost:8007/api/knowledge/profiles`
- **Access Mode**: Read-Only (Creation and deletion actions are redirected to the Ingestion Manager UI on Port 5173).

---

## 3. Key UI Modules & Features

1. **Proxy Profiles Table**: Displays active Knowledge Profiles, source buckets included, and target vector collection destinations.
2. **Target Qdrant Collection Mapper**: Direct link to open the corresponding RAG Pipeline configuration in `/pipelines`.
3. **Ingestion Manager Navigation Banner**: Prompt guiding users to open `http://localhost:5173/knowledge-store` if full editing rights are needed.
