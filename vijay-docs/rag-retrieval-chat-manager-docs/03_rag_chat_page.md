# 03. RAG Chat & Interactive Testing Page (`/chat`)

## 1. Page Purpose & Summary

The **RAG Chat** (`/chat`) page provides an interactive playground for testing vector retrieval quality, prompt template behavior, cross-encoder reranking, LLM answer synthesis, and source citations in real time.

---

## 2. Key UI Modules & Features

1. **Session Sidebar**: List of historical chat sessions with title previews, creation timestamp, message count, and session deletion controls.
2. **Chat Stream Interface**: Rich chat thread rendering markdown responses, code syntax highlighting, and real-time streaming tokens.
3. **Retrieval Controls Drawer**:
   - **Retrieval Mode**: Select `hybrid`, `dense`, or `sparse`.
   - **Reranker Toggle**: Enable/disable Cross-Encoder reranking (`top_k` slider).
   - **LLM Model Selector**: Choose answer generation model (`gpt-4o`, `claude-3-5-sonnet`, `llama3-70b`).
   - **System Prompt Preset**: Dropdown to select active system prompt template from `/prompts`.
4. **Source Citation Inspector**: Interactive drawer opening retrieved text chunks, vector similarity scores, page numbers, and file source locators for generated answers.
5. **Guardrails Moderation Banner**: Displays real-time input/output moderation status and flags blocked responses.

---

## 3. Data Fetching & API Interactions

- **`chatWithPipeline(payload)`**: `POST /api/rag/chat` — Sends user query, session ID, retrieval mode, rerank settings, system prompt choice, and guardrails config ID.
- **`listChatSessions()`**: `GET /api/rag/chat/sessions` — Retrieves list of chat sessions.
- **`getChatSessionMessages(sessionId)`**: `GET /api/rag/chat/sessions/{id}/messages` — Retrieves chat message history for a session.
- **`deleteChatSession(sessionId)`**: `DELETE /api/rag/chat/sessions/{id}` — Deletes a chat session thread.
