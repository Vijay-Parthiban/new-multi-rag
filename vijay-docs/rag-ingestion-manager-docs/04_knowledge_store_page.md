# Knowledge Store Page

## Route
`/knowledge-store`

## Component
`KnowledgeStorePage.tsx`

## Features
Orchestrates the downstream data sync of ingested content into retrieval-ready backends (the RAG memory banks).
- **Universal Multi-Sink Fanout Engine**: 
  - Allows routing parsed/chunked document streams concurrently to 5 destinations: Qdrant, OpenSearch, Neo4j, Postgres, and RedisVL.
- **Knowledge Profiles**: Lists distinct routing configurations (profiles). Shows totals for active endpoints, remote repos, and active RAG sinks.
- **Connection Testing**: UI capable of verifying connections before saving the profile.

## Backend APIs Used
- `GET /api/knowledge-profiles`
- `GET /api/knowledge-profiles/{profile_id}`
- `GET /api/knowledge-profiles/destinations/options`
- `POST /api/knowledge-profiles/{profile_id}/test-connection`
- `POST /api/knowledge-profiles/{profile_id}/sync`