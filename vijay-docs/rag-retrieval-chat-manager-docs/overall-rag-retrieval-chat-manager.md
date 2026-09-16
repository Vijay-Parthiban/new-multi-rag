# RAG Retrieval & Chat Manager - Overall Architecture

The Retrieval & Chat Manager focuses on query execution, LLM generation, prompt management, evaluation, and AI guardrails. It sits downstream from the Ingestion Manager.

## Architecture Components

1. **Frontend (`/frontend`)**
   - React + Vite SPA managed by `AppLayout.tsx`.
   - All pages rendered under a single persistent layout; navigation does not unmount active components.
   - Sidebar routes (from `AppLayout.tsx` NAV array):
     - `/` Overview
     - `/knowledge-store` Knowledge Store
     - `/pipelines` Pipelines
     - `/chat` Chat
     - `/prompts` Prompts
     - `/evaluations` Real Time Monitoring
     - `/golden-evaluations` Offline Evaluation
     - `/tracking` Tracking
     - `/guardrails/config` Guard Config
     - `/guardrails/traces` Guard Traces
     - `/guardrails/evaluation` Guard Evaluation

2. **Backend (`/backend`)**
   - Python FastAPI on port 8001 (`apps/rag-api`).
   - Background eval worker (`apps/eval-worker`).
   - Route modules: `chat`, `retrieve`, `search`, `rerank`, `generate`, `prompts`, `evaluate`, `guardrails`, `guardrails_evaluate`, `knowledge`.

3. **Lib Modules**
   - `database` - SQLAlchemy models: `chat`, `evaluation`, `guardrails`, `prompts`, `pipelines`
   - `retrieval-core` - Vector, graph, BM25 retrieval strategies
   - `generation-core` - LLM streaming and synchronous generation
   - `vector-core` - Qdrant vector operations
   - `reranker-core` - Cross-encoder reranking
   - `eval-core` - RAGAS-based evaluation metrics

4. **Integration via Shared Contracts**
   - `shared-contracts` Pydantic models ensure chunk schemas and knowledge store config objects match ingestion pipeline outputs.

## Backend API Surface

| Module | Prefix | Key Endpoints |
|--------|--------|---------------|
| chat | - | `POST /chat`, `POST /chat/stream`, `GET /chat/stats`, `GET /chat/sessions` |
| evaluate | /evaluate | `POST /datasets`, `POST /datasets/upload`, `GET /datasets`, `POST /runs` |
| guardrails | /guardrails | `GET /guards`, `POST /configs`, `GET /traces`, `POST /evaluate` |
| prompts | /prompts | CRUD for prompt templates |
| retrieve | /retrieve | Vector/graph/hybrid retrieval |
| search | /search | Keyword and semantic search |
| rerank | /rerank | Cross-encoder reranking |
| knowledge | /knowledge | Knowledge profile registration from ingestion |

## Docker Services

| Service | Port | Status |
|---------|------|--------|
| rag-api | 8001 | Configured (not started) |
| eval-worker | - | Configured (not started) |
| Postgres (shared) | 5432 | Running (healthy) |
| Redis (shared) | 6379 | Running (healthy) |
| Qdrant (shared) | 6333 | Running |
