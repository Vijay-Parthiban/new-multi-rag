# RAG Chat Page

## Route
`/chat`

## Component
`ChatPage.tsx`

## Features

Full conversational interface backed by the RAG pipeline.

- **Streaming Chat**: `POST /chat/stream` returns a Server-Sent Events stream for token-by-token LLM output.
- **Source Citations**: Each response includes source document references drawn from retrieval traces.
- **Session Management**: Chat history grouped by session. Sessions listed via `GET /chat/sessions`.
- **Message Metrics**: Per-message latency, retrieval scores, and reranker metrics via `GET /chat/messages/{id}/metrics`.
- **Guardrails Integration**: Pre- and post-retrieval guardrail checks run inline via `_run_guardrails()`. Blocked responses return a safe fallback answer.
- **Chat Stats**: Aggregate stats across all sessions via `GET /chat/stats`.

## Backend APIs Used

- `POST /chat`
- `POST /chat/stream`
- `GET /chat/stats`
- `GET /chat/sessions`
- `GET /chat/sessions/{session_id}/messages`
- `DELETE /chat/sessions/{session_id}`
- `DELETE /chat/messages/{message_id}`
- `GET /chat/messages/{message_id}/metrics`
