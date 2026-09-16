# RAG Pipelines Page

## Route
`/pipelines`

## Component
`PipelinesPage.tsx`

## Features

Configuration interface for assembling RAG retrieval pipelines. Links retrieval algorithms with reranking strategies and LLM generation configs.

- **Pipeline Builder**: Compose retrieval strategy (dense vector via Qdrant, BM25 via OpenSearch, graph traversal via Neo4j, or hybrid combinations).
- **Reranker Config**: Attach cross-encoder reranking step post-retrieval via `reranker-core`.
- **Knowledge Store Binding**: Associate pipeline with a registered Knowledge Profile from the Ingestion Manager.
- **Pipeline Execution**: Trigger test runs against configured sinks.

## Backend APIs Used

- `GET /api/pipelines`
- `POST /api/pipelines`
- `PUT /api/pipelines/{id}`
- `DELETE /api/pipelines/{id}`
- `POST /api/pipelines/{id}/run`
