# 03. Data Sources & Connectors Page (`/sources`)

## 1. Page Purpose & Summary

The **Data Sources & Connectors** (`/sources`) page is the core integration hub of `rag-ingestion-manager`. It manages external data sources (Google Drive, Amazon S3, Google Cloud Storage, Google Sheets, SQL Databases, Web Scrapers, Local Filesystem) and direct sync pipelines feeding into dedicated MinIO S3 storage buckets (`source-<name>-<hash>`).

---

## 2. Key UI Modules & Features

1. **Sources Overview Banner**: Metrics summarizing total active sources, operational status, total synced files, and connected ingestion streams.
2. **Data Source Cards / Table View**:
   - Source Name & Source ID (`/sources/:id`)
   - MinIO Bucket Locator (`source-<name>-<hash>`) or Local Filesystem storage path (`storage/local_sources/<folder>`)
   - Attached Connectors List (type, status badge: `idle`, `synced`, `syncing`, `error`)
   - Action Buttons: `Sync Now`, `View Details` (`/sources/:id`), `Delete Source` (purges bucket and metadata).
3. **Source Detail View (`/sources/:id`)**:
   - Status Metric Cards: `Source Status`, `Attached Connectors`, `Total Synced Files` (with total KB storage size).
   - Interactive Connector Gallery: Google Drive, Amazon S3, Azure Blob Storage, Google Sheets, OneDrive, SQL Database, Web Scraper.
   - Connector Config Modal with JSON / form credential input (Service Account JSON, OAuth credentials, Folder URL/ID).
   - MinIO File Browser Tab: Real-time listing of all objects in the source's bucket with keys, sizes, and modification dates.
4. **Create New Data Source Modal**: Step-by-step wizard to register a new source bucket and attach initial connectors.

---

## 3. Data Fetching & API Interactions

- **`listSources()`**: `GET /api/sources`
  - Fetches all sources along with embedded connector options, `total_files`, `total_size_bytes`, and sync status.
- **`getSource(sourceId)`**: `GET /api/sources/{id}`
  - Retrieves detailed source record, attached connector configurations, and bucket metadata.
- **`listConnectors()`**: `GET /api/sources/connectors`
  - Retrieves catalog of available connector types and default credential schemas.
- **`createSource(body)`**: `POST /api/sources`
  - Creates source record in database and provisions a physical S3 bucket in MinIO via threaded `boto3`.
- **`triggerSourceSync(sourceId)`**: `POST /api/sources/{id}/sync`
  - Dispatches sync job pulling remote files (e.g. Google Drive folder API downloads) directly into MinIO and updating `total_files` and `total_size_bytes`.
- **`listSourceFiles(sourceId)`**: `GET /api/sources/{id}/files`
  - Lists objects inside the source's MinIO bucket (`s3_client.list_objects`).
- **`deleteSource(sourceId)`**: `DELETE /api/sources/{id}`
  - Destroys source record, attached connector configs, and completely purges and deletes the MinIO bucket.

---

## 4. Ingestion Sync Engine Architecture

- **Threaded MinIO S3 Storage (`s3_client.py`)**: All S3/MinIO operations (`put_object`, `get_object`, `head_object`, `list_objects`, `ensure_bucket`, `delete_bucket`) use synchronous `boto3` wrapped in `asyncio.to_thread` to prevent event loop blocking on Windows and ensure socket safety.
- **Google Drive Sync Engine (`gdrive_sync.py`)**: Authenticates via Service Account JSON, lists folder contents recursively via Google Drive API in `asyncio.to_thread`, downloads files, streams them into MinIO (`connectors/{connector_id}/{file_id}/{filename}`), and attaches file metadata.
- **Differential State Tracking**: Sync tracks existing bucket objects and updates `source.total_files` and `source.total_size_bytes` automatically upon completion.
