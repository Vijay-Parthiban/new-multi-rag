# 01 — Ingestion Overview Dashboard Page

**Last updated:** 2026-09-17

## 1. Executive Summary & Page Purpose
The **Ingestion Overview Dashboard** (`HomePage.tsx`, route: `/`) serves as the central mission control and real-time operational dashboard for the `rag-ingestion-manager` application. It provides engineering teams and data administrators with an immediate, high-level pulse on connected data sources, directory workspaces, indexed file counts, and active multi-sink Knowledge Store routing profiles.

---

## 2. UI Layout & Visual Components

```
+---------------------------------------------------------------------------------------+
|  Ingestion Manager   |  Overview  |  Folders  |  Upload  |  Sources  |  Knowledge Store  |
+---------------------------------------------------------------------------------------+
|  Ingestion Overview                                                                   |
|  Ingest documents, manage connected data sources, and orchestrate 5-sink Knowledge    |
|  Store fanout sync.                                                                   |
+---------------------------------------------------------------------------------------+
|  [ Metric Cards: Connected Sources | Workspace Folders | Indexed Files | Profiles ]   |
+---------------------------------------------------------------------------------------+
|  Quick Launch Workspaces:                                                             |
|  [ 📤 Document Upload ]   [ 📁 Data Sources & Storage ]   [ 📂 Folders & Files ]      |
|  [ 🌐 External Connectors ]   [ 🗄️ Knowledge Store Fanout ]                          |
+---------------------------------------------------------------------------------------+
|  Connected Sources Summary Table                                                      |
|  Source Name      | Type     | Bucket / Path | Files | Last Sync | Status             |
|  -----------------+----------+---------------+-------+-----------+------------------- |
|  v-res            | connector| v-res         | 10    | 2m ago    | CONNECTED (Active) |
|  manual-vj        | upload   | manual-vj     | 1     | 5m ago    | CONNECTED (Active) |
+---------------------------------------------------------------------------------------+
```

### Component Hierarchy
- **Header Section (`PageHeader.tsx`)**: Displays page title, description, and status badges.
- **Metric Highlight Panels**:
  - **Connected Data Sources**: Total active and configured source connections (MinIO connectors, manual uploads, Google Drive, S3, etc.).
  - **Workspace Folders**: Count of virtual directory workspaces managed in the metadata store.
  - **Indexed Files**: Aggregated count of documents processed and tracked across all directories.
  - **Knowledge Profiles**: Number of configured 5-destination multi-vector routing profiles.
- **Quick Action Grid** (`HomePage.tsx` → `QUICK_LINKS`):
  - `Document Upload` (`/upload`): Upload PDF, DOCX, CSV, JSON, Markdown, and text to buckets or folders.
  - `Data Sources & Storage` (`/sources`): Manage MinIO buckets and connector-backed sources.
  - `Folders & Files` (`/browse`): Directory workspace and file preview.
  - `External Connectors` (`/sources`): S3, Azure Blob, SFTP, Confluence, and Web Scrapers.
  - `Knowledge Store Fanout` (`/knowledge-store`): 5-sink sync orchestration and live visualizers.
- **Connected Sources Table**: Real-time listing of active data sources with sync timestamps, document counts, and health status badges.

---

## 3. Backend APIs & Data Contracts

| Method | Endpoint | Description | Response Model |
|---|---|---|---|
| `GET` | `/api/sources` | Lists all registered data sources and connectors | `list[SourceRecord]` |
| `GET` | `/api/directories` | Lists virtual workspace directories with file counts | `list[DirectorySummary]` |
| `GET` | `/api/knowledge-profiles` | Lists configured Knowledge Store fanout profiles | `list[KnowledgeProfile]` |
| `GET` | `/api/files/stats` | Aggregates total indexed document count and storage usage | `FileStatsResponse` |

### Sample JSON Response (`GET /api/sources`)
```json
[
  {
    "id": "2da1c0d5-5727-4632-9cb9-009c91d4e0e4",
    "name": "v-res",
    "source_type": "connector",
    "status": "connected",
    "config": {
      "connector_id": "minio",
      "bucket": "v-res",
      "endpoint_url": "http://minio:9000"
    },
    "file_count": 10,
    "last_sync_at": "2026-09-16T08:35:12.834Z"
  },
  {
    "id": "e23cb20a-8a4b-4bfa-a42e-cf6e01a88b50",
    "name": "manual-vj",
    "source_type": "upload",
    "status": "connected",
    "config": {
      "bucket": "manual-vj"
    },
    "file_count": 1,
    "last_sync_at": "2026-09-16T08:42:01.120Z"
  }
]
```

---

## 4. Key Workflows & User Interactions
1. **System Health Verification**: Administrators review metric cards to confirm active data sources and sync status.
2. **One-Click Navigation**: Quick action cards enable direct jumping into directory browsing, source configuration, or Knowledge Store fanout synchronization.
3. **Real-Time Refresh**: The dashboard queries backend services concurrently via `Promise.all` on mount and provides instant visual feedback without UI blocking.
