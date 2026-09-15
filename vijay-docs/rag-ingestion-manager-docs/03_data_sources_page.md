# Data Sources Page

## Route
`/sources`

## Component
`SourcesPage.tsx`

## Features
The primary control plane for defining, listing, and configuring upstream data integrations.
- **Source Grid Overview**: Displays cards for configured integrations, e.g., Google Drive, S3, Azure Blob, SFTP, and Web Scrapers.
- **State Indicators**: Shows whether a source is `Active`, `Syncing`, or `Idle`.
- **Connector Management**: Connectors represent individual tasks running under a source. The grid reveals connector IDs and triggers on-demand sync polls (CDC equivalents).

## Backend APIs Used
- `GET /api/sources`
- `GET /api/sources/{source_id}`
- `POST /api/sources/{source_id}/connectors`
- `POST /api/sources/{source_id}/connectors/{connector_id}/sync`
- `DELETE /api/sources/{source_id}`