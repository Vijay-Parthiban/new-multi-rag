# RAG Ingestion Manager - Overall Architecture

The RAG Ingestion Manager is a FastAPI and React based autonomous microservice cluster responsible for data onboarding, chunking, and knowledge storage delivery (fanout).

## Architecture Components

1. **Frontend (`/frontend`)**
   - React UI using Vite (port 5173).
   - Sidebar navigation with isolated views: Overview, Folders, Sources, Knowledge Store.
   - Persistent state across route transitions via custom `<PersistentPage>` component.

2. **Backend (`/backend`)**
   - Python FastAPI (Uvicorn, port 8007).
   - Routes: `/pipelines`, `/sources`, `/knowledge-profiles`, `/uploads`, `/directories`, `/files`.
   - SQLAlchemy (async) + Alembic migrations on Postgres.
   - Background worker loop pulls from three Redis queues: `file_manager:jobs`, `ingestion:pipeline:jobs`, `ingestion:sync:jobs`.

3. **Storage & State Infrastructure**
   - **MinIO**: S3-compatible blob store. Raw source files land in isolated `source-[uuid]` buckets. Console at port 9001, API at 9000.
   - **Postgres**: Source config, metadata, indexed file records, knowledge profile definitions.
   - **Redis**: Queue broker for all three background job types.
   - **Qdrant**: Dense vector search engine (port 6333, dashboard at /dashboard).
   - **OpenSearch**: Lexical + sparse vector search engine (port 9200).
   - **Neo4j**: Knowledge graph store for GraphRAG entity triples (ports 7474 browser, 7687 bolt).

4. **Integration via Shared Contracts**
   - `shared-contracts` Python library defines Pydantic models: `SourceRecordBase`, `KnowledgeProfileBase`, `KnowledgeDestinationConfigBase`.
   - Ensures consistent serialization between ingestion and retrieval pipelines.

## Data Flow: Source to MinIO to Universal Fanout to 5 Sinks

1. **Connector Extraction** (`apps/worker/main.py`)
   - Worker dequeues from Redis `ingestion:sync:jobs`.
   - Calls `sync_source_from_pathway()` in `pathway_sync.py`.

2. **NiFi Pipeline** (`src/ingestion_service/core/pathway_sync.py`)
   - Validates connector config via `validate_airbyte_connector_config()`.
   - Routes through `sync_connector_via_nifi()` to pull data from external sources (Google Drive, Local FS, APIs).
   - Transfers raw bytes into the source-specific MinIO bucket.
   - After all connectors finish, updates source status to `idle` and calls `_trigger_pipeline_syncs()`.

3. **Fanout Trigger** (`src/ingestion_service/core/universal_fanout.py`)
   - `execute_universal_fanout_sync()` loads the linked `KnowledgeProfile` and its enabled destinations.
   - Downloads raw blobs from MinIO via `list_objects()` + `get_object()`.

4. **Parsing and Embedding**
   - `iter_file_pages()` from `page_yielder.py` chunks documents into structured `FilePage` segments.
   - `EmbeddingClient` generates dense vectors using configured model (nvidia-embed-passage / fastembed).

5. **Multi-Sink Broadcast**
   - Parallel fanout to all enabled destinations in the Knowledge Profile:
     - **Qdrant**: Dense HNSW vectors into `knowledge_qdrant_collection`.
     - **OpenSearch**: BM25 + SPLADE sparse vectors into `knowledge_lexical_index`.
     - **PostgreSQL**: pgvector embeddings + metadata into `knowledge_vector_records`.
     - **RedisVL**: Semantic cache + RAPTOR parent-child trees under prefix `knowledge_cache`.
     - **Neo4j**: Entity-relationship triples for multi-hop GraphRAG (bolt://localhost:7687).

## Live Docker Services (2026-09-16)

| Service         | Port       | Status          |
|-----------------|------------|-----------------|
| Frontend        | 5173       | Running         |
| API             | 8007       | Running         |
| Postgres        | 5432       | Running (healthy)|
| Redis           | 6379       | Running (healthy)|
| MinIO Console   | 9001       | Running         |
| MinIO API       | 9000       | Running         |
| Qdrant          | 6333       | Running         |
| Neo4j Browser   | 7474       | Running         |
| Neo4j Bolt      | 7687       | Running         |
| OpenSearch      | 9200       | Running         |
| NiFi            | 8443       | Configured      |

## Active Knowledge Profile: Multi-RAG Master Profile

Created: 2026-09-16
Linked Sources:
- `v-res` (MinIO bucket: source-v-res-5d2edc8f)
- `manual-vj` (MinIO bucket: source-manual-vj-5f4d24f4)

Enabled Sinks (5/5):
1. Qdrant - Dense vector similarity search (HNSW + scalar/binary quantization)
2. OpenSearch - BM25 keyword matching + SPLADE/BGE-M3 learned sparse vector indexing
3. Neo4j - Entity-relationship extraction + hierarchical GraphRAG community summaries
4. PostgreSQL - ACID-compliant co-located metadata, ACLs, and pgvector embeddings
5. RedisVL - Semantic prompt cache + RAPTOR recursive summary trees
