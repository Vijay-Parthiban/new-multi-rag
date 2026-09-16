# 03 — Interactive RAG Chat & Synthesis Page

## 1. Executive Summary & Page Purpose
The **Interactive RAG Chat & Synthesis Page** (`ChatPage.tsx`, route: `/chat`) is the primary conversational interface. It combines hybrid dense/sparse vector retrieval from Qdrant and OpenSearch, cross-encoder reranking, LLM response synthesis, inline citation rendering, self-corrective router fallbacks, multi-modal image uploads, and real-time AI guardrail enforcement.

---

## 2. UI Layout & Visual Components

```
+---------------------------------------------------------------------------------------------------------+
|  Conversations (Sessions)   |  Chat Window: [ Enterprise Hybrid RAG Pipeline v ] [ Guardrails: On v ]   |
|  -------------------------- |  ------------------------------------------------------------------------ |
|  [ + New Chat ]             |  👤 User:                                                                 |
|                             |  Find senior AI engineers with PyTorch, Neo4j, and Qdrant experience.     |
|  💬 Resume Search - Sept 16 |                                                                           |
|  💬 Technical Architecture  |  🤖 Assistant (Model: gpt-4o | Latency: 1.18s | Route: Normal):            |
|  💬 Financial Reports 2026  |  Based on the indexed resumes, **Alex Chen** is a Senior AI Engineer with |
|                             |  extensive experience in PyTorch, Qdrant vector databases, and Neo4j.     |
|                             |                                                                           |
|                             |  **Cited Sources & Chunk Relevancy**:                                     |
|                             |  - 📄 `resume_alex_chen.pdf` [Chunk #0] (Rerank Score: 0.942) [Inspect]   |
|                             |  - 📄 `resume_elena_rostova.pdf` [Chunk #2] (Rerank Score: 0.811) [Inspect] |
|                             |                                                                           |
|                             |  ------------------------------------------------------------------------ |
|                             |  [ 📎 Attach Image ] [ Type your message...                    ] [ Send ] |
+---------------------------------------------------------------------------------------------------------+
|  Chunk Inspector Drawer (Active Selection):                                                             |
|  Source: resume_alex_chen.pdf | Chunk ID: c6239121-0e10-4107-8898-d89069d3e8e1 | Similarity: 0.942       |
|  Text: "Alex Chen — Senior AI Engineer with extensive experience in Qdrant, Neo4j, and PyTorch..."     |
+---------------------------------------------------------------------------------------------------------+
```

---

## 3. Streaming Chat Protocol & Guardrail Feedback
- **Server-Sent Events (SSE)**: The frontend streams responses token-by-token via `POST /chat/stream` or `POST /chat`.
- **Guardrail Interception & Block Cards**: When an input or output violates active safety policies (e.g. Presidio PII leak, prompt injection, toxic language), the chat renders a distinct `chat-blocked-card` (`BlockedCard` component) displaying:
  - Policy Category Icon (🚫 Banned Word, 🔒 PII Redaction, ⚠️ Toxic Content, 🛡️ Prompt Injection).
  - Clear user-facing explanation of why the message was intercepted.
  - Phase indicator (`Input blocked` vs `Response blocked`).

---

## 4. Backend APIs & Contracts

| Method | Endpoint | Description | Request / Response |
|---|---|---|---|
| `POST` | `/chat` | Non-streaming conversational RAG endpoint | `ChatRequest` -> `ChatResponse` |
| `POST` | `/chat/stream` | Streaming SSE endpoint for real-time tokens | `ChatRequest` -> `EventStream` |
| `GET` | `/chat/sessions` | Lists user chat sessions | `ChatSessionsResponse` |
| `GET` | `/chat/sessions/{session_id}/messages` | Retrieves message history with source citations | `list[ChatMessageItem]` |
| `DELETE` | `/chat/sessions/{session_id}` | Deletes a conversation session | `{"status": "deleted"}` |
| `GET` | `/chat/messages/{message_id}/metrics` | Returns latency breakdown & chunk scores | `RAGMetricsResponse` |

### Sample Streaming Event Payload
```json
{
  "message_id": "8fa1c4d9-0b1a-4f6c-811c-d8f9b87a0c01",
  "token": "Based on the provided documents",
  "route": "normal",
  "latency_ms": 1180,
  "sources": [
    {
      "source_locator": "resumes/resume_alex_chen.pdf",
      "chunk_index": 0,
      "rerank_score": 0.942
    }
  ]
}
```
