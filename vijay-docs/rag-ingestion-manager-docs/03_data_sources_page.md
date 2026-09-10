# 03. Data Sources & Connectors Page (`/sources`)

## 1. Page Purpose & Summary

The **Data Sources & Connectors** (`/sources`) page is the core data ingestion integration hub of `rag-ingestion-manager`. It manages external data sources (Google Drive, Amazon S3, Google Cloud Storage, Google Sheets, SQL Databases, Web Scrapers, Local Filesystem) feeding into dedicated MinIO S3 storage buckets (`source-<name>-<hash>`) or local filesystem directories (`storage/local_sources/<folder>`), featuring automatic continuous live and scheduled background polling.

---

## 2. Key UI Modules & Features

1. **Sources Overview Banner**: Highlights total active sources, connected connectors, total synced files, total storage size, and background synchronization mode summary.
2. **Data Source Cards & Table View**:
   - Source Name & Source ID (`/sources/:id`)
   - MinIO Bucket Locator (`source-<name>-<hash>`) or Local Filesystem directory path
   - Attached Connectors List (type, monitoring mode badge: `LIVE` vs `SCHEDULED`, status: `synced`, `syncing`, `failed`, `idle`)
   - Actions: `Sync Now` (manual trigger), `View Details` (`/sources/:id`), `Delete Source` (purges bucket/directory and metadata).
3. **Source Detail View (`/sources/:id`)**:
   - Status & Configuration Summary: Monitoring mode, sync interval, bucket name, total files, total size bytes.
   - Interactive Connector Gallery: Google Drive, Amazon S3, Azure Blob Storage, Google Sheets, OneDrive, SQL Database, Web Scraper.
   - Connector Configuration Modal: Credential forms / JSON configuration input (Service Account JSON, OAuth tokens, folder IDs).
   - MinIO File Browser Tab: Live object listing of source bucket objects with keys, sizes, and modification dates.
4. **Create New Source Modal**: Step-by-step wizard to provision a new source bucket and attach initial connectors.

---

## 3. Data Fetching & API Interactions

- **`listSources()`**: `GET /api/sources` — Fetches sources, embedded connectors, `connector_monitor_mode`, `connector_sync_interval_minutes`, total file count, total size bytes, and sync status.
- **`getSource(sourceId)`**: `GET /api/sources/{id}` — Retrieves detailed source record, attached connectors, and bucket metadata.
- **`createSource(body)`**: `POST /api/sources` — Creates source in database, provisions MinIO S3 bucket, and calls `register_source_poller(source_id)` to initiate background polling.
- **`updateSource(sourceId, body)`**: `PATCH /api/sources/{id}` — Updates source configuration, monitoring mode, or sync interval, and re-registers the background poller (`register_source_poller(source_id)`).
- **`deleteSource(sourceId)`**: `DELETE /api/sources/{id}` — Stops active poller task (`stop_source_poller(source_id)`), purges MinIO bucket/local directory, and deletes source record from database.
- **`addSourceConnector(sourceId, body)`**: `POST /api/sources/{id}/connectors` — Attaches connector and updates source poller (`register_source_poller`).
- **`updateSourceConnector(sourceId, connectorId, body)`**: `PATCH /api/sources/{id}/connectors/{connector_id}` — Updates connector mode/interval and refreshes poller (`register_source_poller`).
- **`deleteSourceConnector(sourceId, connectorId)`**: `DELETE /api/sources/{id}/connectors/{connector_id}` — Removes connector and updates source poller (`register_source_poller`).
- **`triggerSourceSync(sourceId)`**: `POST /api/sources/{id}/sync` — Performs manual on-demand sync execution.
- **`listSourceFiles(sourceId)`**: `GET /api/sources/{id}/files` — Lists objects stored in the source's MinIO bucket (`s3_client.list_objects`).

---

## 4. Automatic Background Synchronization Engine (`pathway_sync.py`)

- **Instantaneous Live Mode Polling**:
  - Activated when `source.connector_monitor_mode == "live"` or any attached connector is set to `LIVE` mode.
  - Spawns a dedicated continuous background loop running every 3 seconds (<5s sync latency).
- **Precise Scheduled Mode Polling**:
  - Activated when configured in `SCHEDULED` mode.
  - Spawns a background loop executing every `connector_sync_interval_minutes` or connector `sync_interval_minutes` (converted to seconds).
- **FastAPI Startup Hook**:
  - `init_all_source_pollers()` is executed inside `lifespan` in `apps/api/main.py`, automatically loading all enabled sources into continuous background polling loops on server boot.
- **Dynamic Task Lifecycle (`_SOURCE_POLLER_TASKS`)**:
  - `register_source_poller(source_id)` dynamically inspects source mode, cancels any active poller task (`stop_source_poller`), registers the new loop in `_SOURCE_POLLER_TASKS`, and schedules an immediate background initial sync (`_trigger_initial_sync`).
- **Manual "Sync Now" Compatibility**:
  - Manual sync trigger endpoint (`POST /api/sources/{id}/sync`) remains active for instant manual sync execution.
