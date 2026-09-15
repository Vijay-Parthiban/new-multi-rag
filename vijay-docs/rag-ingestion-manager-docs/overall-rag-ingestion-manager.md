# RAG Ingestion Manager - Overall Architecture

The RAG Ingestion Manager is a FastAPI and React based autonomous microservice cluster responsible for data onboarding, chunking, and knowledge storage delivery (fanout).

## Architecture Components

1. **Frontend (`/frontend`)**
   - React UI using Vite (`npm run dev` at 5173).
   - Minimalist layout containing a Sidebar navigation and isolated views (Overview, Folders, Sources, Knowledge Store).
   - Persists state across route transitions via custom `<PersistentPage>` component (e.g. keeps running uploads active during navigation).

2. **Backend (`/backend`)**
   - Python FastAPI application (runs via Uvicorn on 8000/8007).
   - Defines routes for `/pipelines`, `/sources`, `/knowledge-profiles`, `/uploads`, `/directories`, `/files`.
   - Uses SQLAlchemy (async) and Alembic for Database migrations. Postgres is the relational DB of choice.
   - Connects to an orchestrating background worker (Pathway worker pipeline).
   
3. **Storage & State Infrastructure**
   - **MinIO**: S3-compatible blob storage used as the primary raw file datastore (`source-*` buckets). 
   - **Postgres**: Configuration, source connections, and metadata schemas.
   - **Redis**: Rate limiting, pub/sub, caching for FastAPI and celery/worker processes.
   
4. **Integration via Shared Contracts**
   - Depends statically on the `shared-contracts` Python library for defining domain Pydantic models (e.g. `SourceRecordBase`, `KnowledgeProfileBase`, `KnowledgeDestinationConfigBase`).
   - Ensures consistent serialization payloads sent over the wire between the ingestion boundary and retrieval pipelines.
