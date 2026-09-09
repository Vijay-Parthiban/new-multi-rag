# 03. RAG Chat & Interactive Testing Page (`/chat`)

## 1. Page Purpose & Summary

The **RAG Chat** (`/chat`) page provides an interactive playground for testing vector retrieval quality, prompt template behavior, cross-encoder reranking, LLM answer synthesis, and source citations in real time.

---

## 2. Key UI Modules & Features

1. **Session Sidebar**: List of historical chat sessions with title previews, timestamp, message count, and session delete controls.
2. **Chat Stream Interface**: Rich chat thread rendering markdown responses, code blocks, and real-time generation tokens.
3. **Retrieval Controls Drawer**:
   - **Retrieval Mode**: Select `hybrid`, `dense`, or `sparse`.
   - **Reranker Toggle**: Enable/disable Cross-Encoder reranking (`top_k` slider).
   - **LLM Model Selector**: Choose answer generation model (`gpt-4o`, `claude-3-5-sonnet`, `llama3-70b`).
   - **System Prompt Preset**: Dropdown to select active system prompt template from `/prompts`.
4. **Source Citation Inspector**: Interactive drawer opening retrieved text chunks, vector similarity scores, page numbers, and MinIO file links for every generated answer.
5. **Guardrails Moderation Banner**: Displays real-time input/output moderation status and flags blocked responses.

---

## 3. Data Fetching & API Interactions

- **`chatWithPipeline(payload)`**: `POST /api/rag/chat`
  - Sends user query, session ID, retrieval mode, rerank settings, and system prompt choice.
- **`listChatSessions()`**: `GET /api/rag/chat/sessions`
- **`getChatSessionMessages(sessionId)`**: `GET /api/rag/chat/sessions/{id}/messages`
- **`deleteChatSession(sessionId)`**: `DELETE /api/rag/chat/sessions/{id}`
