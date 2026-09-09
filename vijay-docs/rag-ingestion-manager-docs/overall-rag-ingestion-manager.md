# rag-ingestion-manager — Detailed System Documentation

## 1. Executive Summary & Application Scope

The **`rag-ingestion-manager`** is a dedicated full-stack management application focused entirely on document ingestion, directory navigation, connector synchronization, multi-sink Knowledge Store profile management, and chunked resumable file uploads.

- **Frontend UI Port**: `5173` (`http://localhost:5173`)
- **Backend API Port**: `8007` (`http://localhost:8007`)
- **Vite Proxy Rule**: `/api` -> `http://localhost:8007`
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
│ 3. Sources        │ /sources           - Data source CRUD & Airbyte/NiFi connector sync     │
│ 4. Knowledge Store│ /knowledge-store   - Multi-source to multi-destination fanout engine    │
│ 5. Upload         │ /upload            - Resumable 5MB chunked document uploader            │
└───────────────────┴─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Database Schema & Data Models

### 3.1. `sources` Table
| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | UUID (PK) | Primary unique identifier |
| `name` | String(255) | User-friendly source display name |
| `minio_bucket` | String(255) | Dedicated MinIO S3 bucket name (e.g. `bucket-source-123`) |
| `connector_type` | String(100) | Primary connector type (e.g. `google_drive`, `s3`, `local_directory`) |
| `config` | JSONB | Connector credentials and configuration dictionary |
| `status` | String(50) | Ingestion state: `created`, `active`, `syncing`, `failed`, `disabled` |
| `created_at` | DateTime | Creation timestamp |

### 3.2. `source_connectors` Table
Supports multi-connector attachments to a single MinIO source bucket.
| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | UUID (PK) | Unique connector instance identifier |
| `source_id` | UUID (FK) | Reference to `sources.id` |
| `connector_type` | String(100) | Airbyte/NiFi connector type |
| `enabled` | Boolean | Whether active or disabled |
| `config` | JSONB | Connector-specific sync configuration |

### 3.3. `knowledge_profiles` & `knowledge_destinations` Tables
Drives the Universal Multi-Sink Fanout Engine.
- **Profiles**: Groups multiple MinIO source buckets into unified knowledge units.
- **Destinations**: Maps profiles into target database sinks:
  - `vector_search` -> Qdrant Vector DB
  - `relational_db` -> PostgreSQL
  - `document_store` -> Elasticsearch / MongoDB
  - `graph_db` -> Neo4j
  - `data_lake` -> Snowflake / Parquet

---

## 4. Backend API Routes Reference (`http://localhost:8007`)

| Method | Endpoint Path | Description |
| :--- | :--- | :--- |
| `GET` | `/health` | Ingestion API health check endpoint |
| `GET` | `/api/sources` | List all configured data sources & connector counts |
| `POST` | `/api/sources` | Create a new data source & provision MinIO bucket |
| `GET` | `/api/sources/connectors` | Fetch available connector options catalog |
| `POST` | `/api/sources/{id}/sync` | Trigger asynchronous background document sync |
| `DELETE` | `/api/sources/{id}` | Delete source bucket and associated metadata |
| `GET` | `/api/directories` | List root virtual directory summaries |
| `GET` | `/api/directories/{name}/files` | List files within a specified virtual directory |
| `PATCH` | `/api/files/{id}` | Rename a file record |
| `DELETE` | `/api/files/{id}` | Delete a file from MinIO and PostgreSQL |
| `POST` | `/api/uploads/init` | Initialize resumable multi-chunk upload session |
| `PUT` | `/api/uploads/{id}/chunks/{i}` | Upload chunk `i` (5MB payload) |
| `POST` | `/api/uploads/{id}/complete` | Assemble chunks and finalize file record |
| `GET` | `/api/knowledge/profiles` | List all knowledge profiles & destinations |
| `POST` | `/api/knowledge/profiles` | Create new multi-sink knowledge profile |
| `GET` | `/api/knowledge/destinations/options` | Fetch available destination sink options |

---

## 5. How to Run `rag-ingestion-manager` in a New Environment

### 5.1. Start Infrastructure & Backend API
```bash
# 1. Start Docker services (Postgres, MinIO, Redis)
cd new-multi-rag/ingestion-workspace
docker-compose up -d postgres minio redis

# 2. Run backend migrations and start server on port 8007
cd ingestion-backend
source .venv/bin/activate
alembic upgrade head
uvicorn apps.api.main:app --host 0.0.0.0 --port 8007 --reload
```

### 5.2. Start Ingestion Manager Frontend
```bash
cd rag-ingestion-manager/frontend
npm install
npm run dev
# Server will listen on http://localhost:5173
```
