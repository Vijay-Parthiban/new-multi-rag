# Unified RAG Architecture - Overall Detailed Implementation

This document outlines the current working implementation of the Multi-RAG ecosystem. 

The architecture strictly divides tasks into two parallel but integrated systems: **Ingestion** (handling data ingestion, parsing, chunking, storage pipelines) and **Retrieval** (handling query processing, LLM contexts, guardrails, and real-time chat).

## 1. System Topology

### RAG Ingestion Manager (`/rag-ingestion-manager`)
- **Mission:** Read remote configurations, pull data, chunk it, and save it into search-ready schemas (Vector DBs, Text DBs, Relational stores).
- **Backend Stack:** FastAPI, SQLAlchemy (Async PostgreSQL for metadata), Redis, Alembic.
- **Frontend Stack:** React, Vite, React-Router orchestrating isolated tabs for Pipelines, Folders, and Knowledge profiles.
- **Data Flow:** Object files go to **MinIO** buckets. Text mapping routes into **Pathway Worker** or native pipeline instances orchestrating 5-sink fanouts to destinations like Qdrant/OpenSearch.

### RAG Retrieval Chat Manager (`/rag-retrieval-chat-manager`)
- **Mission:** Fetch from sinks properly mapped by ingestion, hydrate context layers with guardrails evaluation, output via streaming integrations (OpenAI/Ollama).
- **Backend Stack:** Micro-layered Python packages (`retrieval-core`, `generation-core`, `eval-core`, `vector-core`). Exposes `rag-api` and runs async jobs via `eval-worker`.
- **Frontend Stack:** React, Vite SPA navigating comprehensive Chat playgrounds, Traces logs, and Guardrail configs.

### Shared Interacts (`/shared-contracts`)
- **Mission:** A dedicated Python wheel containing universal domain objects (e.g. `Pydantic` `SourceRecordBase`, `KnowledgeProfile`).
- **Effect:** Prevents API drift. The Chat component intrinsically understands the storage shapes output by the Ingestion component.

### Security layer (`/guardrails-service`)
- **Mission:** Standalone evaluation server. Validates data passing through Chat interfaces ensuring constraints on PII blocks and topic toxicity. Mounted locally into the system's `docker-compose.yaml`.

## 2. Unwanted Legacy Components
Cruft code from pre-migration (such as `rag-app-workspace` and `ingestion-workspace`) have historically polluted the root mapping but the core workflows are currently contained exclusively in the strictly segmented ingestion/retrieval packages. All interactions are containerized locally for robust portability.