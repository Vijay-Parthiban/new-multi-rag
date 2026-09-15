# RAG Retrieval & Chat Manager - Overall Architecture

The Retrieval & Chat Manager focuses strictly on query execution, LLM generation, dynamic prompt management, and AI guardrails evaluation. It sits downstream from the Ingestion Manager.

## Architecture Components

1. **Frontend (`/frontend`)**
   - React UI using Vite (`npm run dev`).
   - Unified persistent-page Single Page Application layout managed by `AppLayout.tsx`.
   - Complete navigation suite orchestrating pipelines, chat, prompts, traces, and guardrail validations natively.

2. **Backend (`/backend`)**
   - Heavily modularized Python codebase split into isolated domains:
     - **Apps**: `rag-api` (Main RAG API), `eval-worker` (Evaluation tasks).
     - **Libs**: `database`, `retrieval-core`, `generation-core`, `vector-core`, `reranker-core`, `eval-core`.
   - Fully decoupled logic: separating retrieval (Vector/Graph/BM25) from Generation (LLM endpoints, Streaming).

3. **Backend RAG Endpoints (`rag-api`)**
   - Generation: `POST /api/chat/stream`, `POST /api/generate`, `DELETE /api/chat/messages/{message_id}`
   - Retrieval/Search: `GET /api/search`, `POST /api/scrapes/query`, `POST /api/rerank`
   - Evaluation & Testing: `/api/runs`, `/api/datasets`, `/api/datasets/upload`
   - Guardrails: `/api/guards`, `/api/traces`, `/api/configs`

4. **Integration via Shared Contracts**
   - Depends statically on `shared-contracts` package for definitions ensuring consistency with the upstream Ingestion Pipeline outputs (especially chunk schemas and knowledge store configuration objects).