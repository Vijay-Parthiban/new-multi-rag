# Knowledge Store Page (Retrieval Manager)

## Route
`/knowledge-store`

## Component
`KnowledgeStorePage.tsx`

## Features

Allows the Retrieval Manager to register and reference Knowledge Profiles created by the Ingestion Manager. This avoids cross-service coupling by giving the retrieval side its own local registry of sink connection details.

- **Profile Registration**: Register an ingestion-side Knowledge Profile by providing the same sink connection configs (Qdrant collection, OpenSearch index, Neo4j URI, Postgres table, Redis prefix).
- **Connection Test**: Verify each sink is reachable before binding it to a retrieval pipeline.
- **Sync**: Trigger a lightweight connection refresh to confirm sink schemas match expected retrieval formats.

## Registered Sinks (matching ingestion profile)

| Sink       | Config                        |
|------------|-------------------------------|
| Qdrant     | `knowledge_qdrant_collection` |
| OpenSearch | `knowledge_lexical_index`     |
| Neo4j      | bolt://localhost:7687         |
| PostgreSQL | `knowledge_vector_records`    |
| RedisVL    | `knowledge_cache`             |

## Backend APIs Used

- `GET /api/knowledge`
- `POST /api/knowledge`
- `POST /api/knowledge/{profile_id}/test-connection`
- `POST /api/knowledge/{profile_id}/sync`
