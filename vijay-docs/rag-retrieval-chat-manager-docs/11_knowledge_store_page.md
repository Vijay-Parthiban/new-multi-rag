# Knowledge Store Page

## Route
`/knowledge-store`

## Features
Sync configuration mimicking the Ingestion knowledge store, allowing the Retrieval application to formally register definitions of Sinks outputted by Ingestion (e.g., matching the Postgres or Qdrant connection schemas) avoiding cross-talk.

## Backend APIs Used
- `GET /api/{profile_id}`
- `POST /api/{profile_id}/sync`
- `POST /api/{profile_id}/test-connection`