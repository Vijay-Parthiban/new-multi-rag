# Overview Dashboard Page

## Route
`/`

## Component
`OverviewPage.tsx`

## Features

Landing page giving a bird's-eye view of the ingestion system health.

- **System Stats Cards**: Total sources, active Knowledge Profiles, files ingested, bytes stored.
- **Sink Status Indicators**: Quick health check display for all 5 downstream sinks (Qdrant, OpenSearch, Neo4j, Postgres, RedisVL).
- **Recent Activity Feed**: Last N sync events drawn from the backend activity log.
- **Quick Actions**: Shortcuts to create a new source, upload a document, or create a Knowledge Profile.

## Backend APIs Used

- `GET /api/overview/stats`
- `GET /api/overview/recent-activity`
