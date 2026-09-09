# 01. Ingestion Overview Dashboard Page (`/`)

## 1. Page Purpose & Summary

The **Ingestion Overview Dashboard** (`/`) is the central landing screen of the `rag-ingestion-manager` application. It provides real-time monitoring of document ingestion pipelines, active storage sources, directory file counts, and overall system health.

---

## 2. Key UI Modules & Widgets

1. **System Health Status Banner**: Displays API operational status (`http://localhost:8007/health`), active database connections, and MinIO storage service readiness.
2. **Key Metric Summary Cards**:
   - **Total Sources**: Total configured external data source buckets.
   - **Active Directory Folders**: Total root virtual directories created.
   - **Knowledge Store Profiles**: Count of active multi-sink knowledge profiles.
   - **Ingestion Workers**: Count of running background sync workers.
3. **Recent Data Sources Grid**: Compact view of the latest created storage buckets, status indicators (`active`, `syncing`, `failed`), and quick navigation links to `/sources`.
4. **Quick Upload CTA**: Direct action button jumping to the `/upload` page for uploading new files.

---

## 3. Data Fetching & API Interactions

- **Endpoint**: `GET /api/sources`
  - Fetches complete list of source buckets for calculating total sources & active counts.
- **Endpoint**: `GET /api/directories`
  - Retrieves virtual directories for directory count summaries.
- **Endpoint**: `GET /api/knowledge/profiles`
  - Obtains knowledge profile statistics.
- **Endpoint**: `GET /health`
  - Polled periodically to ensure backend services are live.

---

## 4. State Management & Data Flow

- React State: `loading` (boolean), `error` (ApiError | null), `sources` (SourceRecord[]), `directories` (DirectorySummary[]), `profiles` (KnowledgeProfile[]).
- Error Handling: Wrapped in `toApiError()` to display inline warning banners if any backend endpoint is unreachable.
