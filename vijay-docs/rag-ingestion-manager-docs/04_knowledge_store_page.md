# Knowledge Store Page

## Route
`/knowledge-store`

## Component
`KnowledgeStorePage.tsx`

## Features

Orchestrates downstream sync of ingested content into retrieval-ready backends via the Universal RAG Ingestion Multi-Sink Fanout Engine.

- **Universal Multi-Sink Fanout Engine**: Routes parsed/chunked document streams concurrently to 5 destinations: Qdrant, OpenSearch, Neo4j, Postgres, and RedisVL.
- **Knowledge Profiles**: Lists distinct routing configurations. Shows `IDLE` / `SYNCING` status, linked MinIO buckets, and configured destination sinks.
- **Connection Testing**: Pings each configured sink endpoint before saving (Qdrant REST, Neo4j bolt, OpenSearch HTTP, Postgres TCP, Redis ping).
- **Sync Execution**: "Sync All Sinks" triggers `POST /api/knowledge-profiles/{profile_id}/sync`, which queues `_background_fanout_sync(profile_id)` on the worker calling `execute_universal_fanout_sync()`.

## Active Profile: Multi-RAG Master Profile

| Destination | Type            | Endpoint                  | Config Key                  |
|-------------|-----------------|---------------------------|-----------------------------|
| Qdrant      | Vector Engine   | http://localhost:6333     | `knowledge_qdrant_collection` |
| OpenSearch  | Lexical Engine  | http://localhost:9200     | `knowledge_lexical_index`     |
| Neo4j       | Graph Store     | bolt://localhost:7687     | -                             |
| PostgreSQL  | DB + pgvector   | localhost:5432            | `knowledge_vector_records`    |
| RedisVL     | Semantic Cache  | redis://localhost:6379    | `knowledge_cache`             |

## Sink-Specific Config Defaults (from `knowledge.py` route defaults)

**Qdrant**
- vector_size: 384
- distance: Cosine
- hnsw_m: 16
- hnsw_ef_construct: 100
- quantization: int8_scalar

**OpenSearch**
- bm25_k1: 1.2
- bm25_b: 0.75
- sparse_model: bge-m3-sparse

**PostgreSQL**
- index_algorithm: DiskANN
- distance_op: vector_cosine_ops
- schema_name: public

**RedisVL**
- similarity_threshold: 0.15
- ttl_seconds: 86400
- parent_child_mapping: true

## Backend APIs Used

- `GET /api/knowledge-profiles`
- `GET /api/knowledge-profiles/{profile_id}`
- `GET /api/knowledge-profiles/destinations/options`
- `POST /api/knowledge-profiles/{profile_id}/test-connection`
- `POST /api/knowledge-profiles/{profile_id}/sync`
