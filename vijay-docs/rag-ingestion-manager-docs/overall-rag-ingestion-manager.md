# rag-ingestion-manager — Detailed System Documentation

## 1. Executive Summary & Application Scope

The **`rag-ingestion-manager`** is a dedicated full-stack management application focused on document ingestion, directory navigation, connector synchronization, multi-sink Knowledge Store profile management, and chunked resumable file uploads.

- **Frontend UI Port**: `5173` (`http://localhost:5173`)
- **Backend API Port**: `8007` (`http://localhost:8007`)
- **Vite Proxy Rule**: `/api` -> `http://127.0.0.1:8007`
- **Domain Boundary**: Restricted strictly to 5 ingestion-specific navigation pages.

---

## 2. Navigation Structure (5 Pages)

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 RAG INGESTION MANAGER UI (5173)                             │
├───────────────────┬─────────────────────────────────────────────────────────────────────────┤
│ Sidebar Link      │ Route Path & Description                                                │
├───────────────────┼─────────────────────────────────────────────────────────────────────────┤
│ 1. Overview       │ /                  - Key ingestion metrics & system health summary      │
│ 2. Folders        │ /browse            - MinIO bucket directory structure & file browser    │
│ 3. Sources        │ /sources           - Data source CRUD & Google Drive/S3/NiFi connector sync │
│ 4. Knowledge Store│ /knowledge-store   - Multi-source to 5 multi-destination fanout engine   │
│ 5. Upload         │ /upload            - Resumable 5MB chunked document uploader            │
└───────────────────┴─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Database Schema & Core Data Models

### 3.1. `sources` Table
| Column | Type | Description |
|---|---|---|
| `id` | `UUID` | Primary key identifier |
| `name` | `VARCHAR(255)` | User-assigned source display name |
| `minio_bucket` | `VARCHAR(255)` | Unique MinIO S3 bucket locator (`source-<name>-<hash>`) |
| `status` | `VARCHAR(50)` | Source sync state (`idle`, `syncing`, `error`) |
| `total_files` | `INTEGER` | Count of active documents synced in the source bucket |
| `total_size_bytes` | `BIGINT` | Total storage volume in bytes across synced files |
| `created_at` | `TIMESTAMP` | Record creation timestamp |
| `updated_at` | `TIMESTAMP` | Last metadata or sync update timestamp |

### 3.2. `source_connectors` Table
| Column | Type | Description |
|---|---|---|
| `id` | `UUID` | Primary key identifier |
| `source_id` | `UUID` | Foreign key referencing `sources.id` |
| `connector_type` | `VARCHAR(50)` | Connector implementation type (`google_drive`, `s3`, `azure_blob`, `local_folder`) |
| `config` | `JSON` | Encrypted credential payload (Service Account JSON, OAuth, Folder URL/ID) |
| `monitor_mode` | `VARCHAR(50)` | Execution trigger policy (`live`, `scheduled`, `manual`) |
| `sync_interval_minutes`| `INTEGER` | Polling schedule interval for scheduled mode |
| `status` | `VARCHAR(50)` | Connector execution status (`synced`, `syncing`, `error`) |
| `last_sync_at` | `TIMESTAMP` | Timestamp of last successful sync execution |

---

## 4. Ingestion Engine Architecture

- **Threaded MinIO S3 Operations (`s3_client.py`)**: Synchronous `boto3` operations wrapped in `asyncio.to_thread` for non-blocking execution and event loop stability under Windows asyncio.
- **Google Drive Sync Engine (`gdrive_sync.py`)**: Direct Drive API integration with `asyncio.to_thread` execution for recursive folder listing and file downloads into MinIO.
- **Universal Multi-Sink Fanout Engine (`universal_fanout.py`)**: Fans out documents across 5 destinations:
  1. Qdrant (Dense & Sparse Vector Store)
  2. OpenSearch (Lexical BM25 & SPLADE)
  3. Neo4j (Knowledge Graphs & Entities)
  4. PostgreSQL (`pgvector` / `pgvectorscale`)
  5. RedisVL (Semantic Cache & Summary Maps)
