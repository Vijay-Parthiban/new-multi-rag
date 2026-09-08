# Ingestion Backend — Architecture & System Design

## Overview

The ingestion backend ingests documents from **two sources**:

1. **Direct file uploads** — users upload PDFs, docs, images via the frontend. Files land in MinIO (per-directory buckets), indexed into Qdrant vector collections.
2. **External data sources & connectors** — Airbyte and Pathway connectors pull data from Google Drive, Amazon S3, Azure Blob, Confluence, databases, etc. into dedicated per-source MinIO buckets (`source-{name}-{id}`). Differential state sync automatically mirrors ADD, UPDATE/REPLACE, and DELETE changes to MinIO.

Both paths feed into the same **RAG pipeline**: chunk -> embed -> upsert to Qdrant.

---

## Service Components & Topology

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Docker Compose                               │
│                                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │   API    │  │  Worker  │  │Pathway Worker│  │  Migrate     │    │
│  │ :8007    │  │ (bg)     │  │ (bg)         │  │ (one-shot)   │    │
│  └────┬─────┘  └────┬─────┘  └──────┬───────┘  └──────────────┘    │
│       │             │              │                                │
│  ┌────┴─────────────┴──────────────┴──────────────────────────┐     │
│  │                    PostgreSQL :5432                        │     │
│  └────────────────────────────────────────────────────────────┘     │
│  ┌────────────────────────────────────────────────────────────┐     │
│  │                    Redis :6379                             │     │
│  └────────────────────────────────────────────────────────────┘     │
│  ┌────────────────────────────────────────────────────────────┐     │
│  │                    MinIO :9000                             │     │
│  └────────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Differential State CRUD Engine (`gdrive_sync.py` & `pathway_sync.py`)

### 1. Multi-Connector Bucket Isolation
Each source has a dedicated MinIO bucket named `source-{source_name}-{source_id[:8]}`. Inside the bucket, objects are namespaced per connector:
```
connectors/{connector_id}/{remote_file_id}/{filename}
```

### 2. Differential CRUD Synchronization Steps
- **ADD**: New remote files are downloaded and stored in MinIO with metadata (`gdrive-file-id`, `remote-modified-at`, `source-id`, `connector-id`).
- **UPDATE / REPLACE**: Overwrites existing MinIO objects when `remote-modified-at` timestamp changes.
- **OBSOLETE KEY REMOVAL**: Automatically deletes old keys when filenames or paths change.
- **DELETE**: Deletes objects from MinIO when remote file IDs no longer exist in the source folder.

### 3. Background Poller Lifecycle
Background pollers are initialized on FastAPI server startup via `init_all_live_sync_pollers()` in `apps/api/main.py`:
```python
@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_storage_layout()
    from src.ingestion_service.core.pathway_sync import init_all_live_sync_pollers
    asyncio.create_task(init_all_live_sync_pollers())
    yield
    await close_redis()
    await close_db()
```

---

## Module Structure

```
ingestion-backend/
├── apps/
│   └── api/
│       ├── main.py                  # FastAPI application entrypoint & lifespan
│       └── routes/
│           ├── sources.py           # Source & connector CRUD endpoints
│           ├── files.py             # File upload & retrieval endpoints
│           └── pipelines.py         # RAG pipeline management endpoints
├── src/
│   ├── ingestion_service/
│   │   └── core/
│   │       ├── gdrive_sync.py       # Google Drive differential CRUD sync engine
│   │       ├── pathway_sync.py      # Pathway sync pollers & concurrency controls
│   │       └── airbyte_connector.py # Airbyte connector configurations
│   └── shared/
│       ├── config/settings.py       # Pydantic system settings & minio_region
│       ├── db/models.py             # SQLAlchemy models (Source, SourceConnector)
│       └── storage/s3_client.py     # Async S3 MinIO storage client
└── pyproject.toml                   # Python dependencies & hatchling build config
```
