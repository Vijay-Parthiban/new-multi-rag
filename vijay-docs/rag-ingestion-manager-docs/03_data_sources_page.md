# 03. Data Sources & Connectors Page (`/sources`)

## 1. Page Purpose & Summary

The **Data Sources & Connectors** (`/sources`) page is the core integration hub of `rag-ingestion-manager`. It manages external data sources (Google Drive, Amazon S3, Google Cloud Storage, Google Sheets, SQL Databases, Web Scrapers) and Airbyte/Apache NiFi connector pipelines feeding into dedicated MinIO S3 storage buckets.

---

## 2. Key UI Modules & Features

1. **Sources Overview Banner**: Metrics summarizing total sources, operational count, and active connector syncs.
2. **Data Source Cards / Table View**:
   - Source Name & Source ID
   - MinIO Bucket Locator (`bucket-<name>`)
   - Attached Connectors List (type, status badge)
   - Action Buttons: `Sync Now`, `View Details` (`/sources/:id`), `Delete Source`.
3. **Create New Data Source Modal**: Step-by-step wizard to register a new source bucket and attach initial connectors.
4. **Connector Catalog Modal**: Interactive gallery of available connectors (Google Drive, S3, GCS, Sheets, Database, Web Scraper) populated from `/api/sources/connectors`.

---

## 3. Data Fetching & API Interactions

- **`listSources()`**: `GET /api/sources`
  - Fetches all sources along with embedded connector options and sync status.
- **`listConnectors()`**: `GET /api/sources/connectors`
  - Retrieves catalog of available connector types and default credential schemas.
- **`createSource(body)`**: `POST /api/sources`
  - Creates source record in database and provisions a physical S3 bucket in MinIO.
- **`triggerSourceSync(sourceId)`**: `POST /api/sources/{id}/sync`
  - Dispatches an asynchronous sync job to pull remote files into the MinIO bucket.
- **`deleteSource(sourceId)`**: `DELETE /api/sources/{id}`
  - Destroys source record, attached connector configs, and purges MinIO bucket contents.

---

## 4. Frontend-Backend Architecture Safeguard

All API calls in `/sources` use relative paths via `apiFetch()` (`/api/sources`), leveraging Vite's server proxy (`server.proxy` -> `http://localhost:8007`). This eliminates CORS preflight errors and hostname resolution mismatches.
