# Data Sources Page

## Route
`/sources`

## Component
`SourcesPage.tsx` / `SourceDetailPage.tsx`

## Features

Manages the full lifecycle of data source connectors that feed raw files into MinIO buckets.

- **Source List**: Displays all configured sources with status (`idle`, `syncing`, `error`), file count, and last sync timestamp.
- **Connector Types Supported**: Google Drive, Local Filesystem, MinIO (manual bucket), Web Scraper, and generic Airbyte-compatible connectors.
- **Per-Source Detail** (`/sources/:id`): Shows connector config, sync history, file browser for the linked MinIO bucket, and manual sync trigger.
- **Monitoring Modes**: `SCHEDULED` (cron interval) or `LIVE` (continuous polling via `start_live_sync_poller()`).
- **MinIO Bucket Isolation**: Each source gets its own `source-[uuid]` MinIO bucket. File listing uses `list_objects()` from `s3_client.py`.

## Currently Active Sources

| Name       | Connector Type  | MinIO Bucket                 |
|------------|-----------------|------------------------------|
| v-res      | MinIO Connector | source-v-res-5d2edc8f        |
| manual-vj  | MinIO Manual    | source-manual-vj-5f4d24f4    |

## Sync Flow

1. `POST /api/sources/{id}/sync` enqueues job to Redis `ingestion:sync:jobs`.
2. Worker calls `sync_source_from_pathway()` in `pathway_sync.py`.
3. Connector validation via `validate_airbyte_connector_config()`.
4. `sync_connector_via_nifi()` pulls external data into the source MinIO bucket.
5. On completion, `_trigger_pipeline_syncs()` fires `execute_universal_fanout_sync()` for all linked Knowledge Profiles.

## Backend APIs Used

- `GET /api/sources`
- `GET /api/sources/{id}`
- `POST /api/sources`
- `PUT /api/sources/{id}`
- `DELETE /api/sources/{id}`
- `POST /api/sources/{id}/sync`
- `GET /api/sources/{id}/files`
