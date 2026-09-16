# Multi-RAG Platform - Overall Detailed Architecture

## Project Structure

```
new-multi-rag/
    rag-ingestion-manager/      # Data ingestion microservice
    rag-retrieval-chat-manager/ # RAG retrieval and chat microservice
    shared-contracts/           # Shared Pydantic models
    shared-libs/                # Shared utilities
    vijay-docs/                 # Architecture documentation
    otel/                       # OpenTelemetry collector config
    guardrails-service/         # AI guardrails service
```

## Microservice Boundaries

### rag-ingestion-manager
Responsible for all data ingestion, chunking, embedding, and multi-sink fanout.
- Backend: FastAPI on port 8007
- Frontend: React/Vite on port 5173
- Worker: Redis-backed background processor

### rag-retrieval-chat-manager
Responsible for RAG pipelines, chat interfaces, evaluation, and guardrails.
- Backend: FastAPI on port 8001
- Frontend: React/Vite on port 5174

## Infrastructure Stack (All running via Docker)

| Component       | Image                                    | Port(s)        | Purpose                                |
|-----------------|------------------------------------------|----------------|----------------------------------------|
| Postgres        | postgres:16-alpine                       | 5432           | Relational config + pgvector           |
| Redis           | redis:7-alpine                           | 6379           | Queue broker + cache                   |
| MinIO           | minio/minio:2024-01-16                   | 9000, 9001     | Raw document blob store                |
| Qdrant          | qdrant/qdrant:v1.18.0                    | 6333           | Dense vector search                    |
| OpenSearch      | opensearchproject/opensearch:2.11.0      | 9200, 9600     | Lexical + sparse vector search         |
| Neo4j           | neo4j:5.15.0                             | 7474, 7687     | Knowledge graph for GraphRAG           |
| NiFi            | apache/nifi:1.24.0                       | 8443           | Connector polling engine               |
| OTel Collector  | otel/opentelemetry-collector:0.148.0     | 4317, 4318     | Distributed tracing                    |

## Ingestion Pipeline (End-to-End)

```
Source (GDrive / LocalFS / MinIO)
    |
    v
NiFi Connector Engine (sync_connector_via_nifi)
    |
    v
MinIO source-[uuid] bucket (raw files)
    |
    v
Universal Fanout Engine (execute_universal_fanout_sync)
    |
    +-- iter_file_pages() + EmbeddingClient
    |
    +--> Qdrant (knowledge_qdrant_collection)    -- dense HNSW vectors
    +--> OpenSearch (knowledge_lexical_index)    -- BM25 + SPLADE sparse
    +--> PostgreSQL (knowledge_vector_records)   -- pgvector + metadata
    +--> RedisVL (knowledge_cache:*)             -- semantic cache + RAPTOR
    +--> Neo4j (bolt://localhost:7687)           -- entity triples + GraphRAG
```

## Active Knowledge Profile: Multi-RAG Master Profile (2026-09-16)

Linked MinIO sources:
- v-res (source-v-res-5d2edc8f)
- manual-vj (source-manual-vj-5f4d24f4)

All 5 sinks enabled and containers running.

## Sink Visualization Access

| Sink        | Tool                  | URL / Connection                    |
|-------------|-----------------------|-------------------------------------|
| Qdrant      | Qdrant Web Dashboard  | http://localhost:6333/dashboard     |
| OpenSearch  | OpenSearch Dashboards | http://localhost:5601 (if running)  |
| Neo4j       | Neo4j Browser         | http://localhost:7474               |
| PostgreSQL  | DBeaver / pgAdmin     | localhost:5432, db: ingestion       |
| RedisVL     | RedisInsight          | localhost:6379                      |
| MinIO       | MinIO Console         | http://localhost:9001               |
