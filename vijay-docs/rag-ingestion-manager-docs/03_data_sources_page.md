# 03 — Data Sources & Connectors Page

## 1. Executive Summary & Page Purpose
The **Data Sources & Connectors Page** (`SourcesPage.tsx`, route: `/sources` and `SourceDetailPage.tsx`, route: `/sources/:id`) manages the ingestion perimeter. It provides unified configuration for **MinIO Connector Buckets**, **Manual Upload Buckets**, and **External Enterprise Connectors** (Google Drive, AWS S3, Azure Blob, SFTP, Web Scrapers, Confluence, PostgreSQL/MySQL CDC). It controls background synchronization jobs, Airbyte/Pathway integration, and source-level health checks.

---

## 2. UI Layout & Visual Components

```
+-----------------------------------------------------------------------------------------------+
|  Data Sources & Connectors                                                                    |
|  Manage remote buckets, scheduled sync pollers, and multi-format document connectors.         |
|  [ + New Data Source ]  [ Refresh ]                                                           |
+-----------------------------------------------------------------------------------------------+
|  Active Sources (2)                                                                           |
|                                                                                               |
|  +--------------------------------------------+  +------------------------------------------+ |
|  | 🪣 v-res                                  |  | 📁 manual-vj                             | |
|  | Type: MinIO Connector (External Source)    |  | Type: Manual Upload Bucket               | |
|  | Bucket: v-res                              |  | Bucket: manual-vj                        | |
|  | Files: 10 documents                        |  | Files: 1 document                        | |
|  | Last Sync: 2 mins ago                      |  | Last Sync: 5 mins ago                    | |
|  | Status: [ CONNECTED ]                      |  | Status: [ CONNECTED ]                    | |
|  |                                            |  |                                          | |
|  | [ 🔄 Sync Now ]  [ 📂 Browse Files ]  [ 🗑️ ]|  | [ 🔄 Sync Now ] [ 📂 Browse Files ] [ 🗑️ ]| |
|  +--------------------------------------------+  +------------------------------------------+ |
+-----------------------------------------------------------------------------------------------+
|  Available Enterprise Connector Catalog:                                                      |
|  [ Google Drive ] [ AWS S3 ] [ Azure Blob ] [ SFTP ] [ Web Scraper ] [ Confluence / Notion ]   |
+-----------------------------------------------------------------------------------------------+
```

### Connector Types & Catalog
- **MinIO S3 Buckets (`connector_id: "minio"`)**: Syncs documents from local or remote S3-compatible MinIO object stores.
- **Manual Upload Buckets (`type: "upload"`)**: Dedicated staging areas for drag-and-drop file ingestion via the browser.
- **Google Drive (`connector_id: "gdrive"`)**: OAuth2 / Service Account service syncing shared drives and docs.
- **AWS S3 / Azure Blob Storage**: Enterprise cloud object store synchronizers.
- **Web Scraper & Crawler (`connector_id: "web_scraper"`)**: Autonomous crawler extracting HTML into structured markdown.
- **Confluence / Notion / SharePoint**: Knowledge base extractors.

---

## 3. Backend APIs & Data Contracts

| Method | Endpoint | Description | Request / Response Payload |
|---|---|---|---|
| `GET` | `/api/sources` | Lists all configured sources | `list[SourceRecord]` |
| `POST` | `/api/sources` | Registers a new source / connector | `SourceCreateRequest` -> `SourceRecord` |
| `GET` | `/api/sources/{id}` | Retrieves full source details & config | `SourceRecord` |
| `PUT` | `/api/sources/{id}` | Updates source configuration / sync interval | `SourceUpdateRequest` -> `SourceRecord` |
| `DELETE` | `/api/sources/{id}` | Removes source and unlinks associated profiles | `{"status": "deleted"}` |
| `POST` | `/api/sources/{id}/sync` | Triggers immediate background sync job | `{"status": "sync_triggered"}` |
| `POST` | `/api/sources/{id}/test` | Validates credentials & bucket reachability | `{"status": "success", "message": str}` |

### Sample Creation Payload (`POST /api/sources`)
```json
{
  "name": "v-res",
  "source_type": "connector",
  "config": {
    "connector_id": "minio",
    "endpoint_url": "http://minio:9000",
    "bucket": "v-res",
    "access_key": "minioadmin",
    "secret_key": "minioadmin",
    "secure": false
  },
  "sync_interval_minutes": 15
}
```

---

## 4. Key Workflows & Data Synchronization
1. **Source Registration**: The administrator selects a connector from the catalog, inputs connection parameters (bucket name, credentials, endpoint URL), and defines optional sync schedules.
2. **Connectivity Validation**: Clicking "Test Link" checks the remote bucket or API endpoint before saving.
3. **Background Sync Runner (`sync_runner.py` / `pathway_sync.py`)**:
   - Downloads new or modified files from MinIO/S3 into the staging layer.
   - Calculates SHA-256 hashes to prevent redundant processing.
   - Triggers automatic document extraction, chunking, and metadata persistence.
