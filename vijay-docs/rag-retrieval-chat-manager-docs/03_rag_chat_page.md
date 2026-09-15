# RAG Chat Page

## Route
`/chat`

## Features
The core chat playground testing retrieval accuracy against the language model generation.
- Real-time streaming UI connecting to the actual RAG engine.
- Supports deletion of specific conversational messages (`DELETE /api/chat/messages/{message_id}`).

## Backend APIs Used
- `POST /api/chat/stream`
- `DELETE /api/chat/messages/{message_id}`