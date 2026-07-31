# Ingestion Backend — Architecture

## Overview

The ingestion backend ingests documents from **two sources**:

1. **Direct file uploads** — users upload PDFs, docs, images via the frontend. Files land in MinIO (per-directory buckets), indexed into Qdrant vector collections.
2. **External data sources** — Airbyte/Pathway connectors pull data from Google Drive, S3, Confluence, databases, etc. into per-source MinIO buckets. Pipeline re-indexing is triggered automatically when new data arrives.

Both paths feed into the same **RAG pipeline**: chunk → embed → upsert to Qdrant.

---

## Service Components

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Docker Compose                                │
│                                                                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │   API     │  │  Worker   │  │Pathway Worker│  │  Migrate     │    │
│  │ :8007     │  │ (bg)      │  │ (bg)         │  │ (one-shot)   │    │
│  └────┬─────┘  └────┬─────┘  └──────┬───────┘  └──────────────┘    │
│       │              │               │                                │
│  ┌────┴──────────────┴───────────────┴──────────────────────────┐   │
│  │                    PostgreSQL :5432                           │   │
│  └──────────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    Redis :6379                                │   │
│  └──────────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    MinIO :9000                                │   │
│  └──────────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    Qdrant :6333                               │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               │
│  │ Scraper API  │  │Scraper Worker│  │Scraper Migrate│               │
│  │ :8000         │  │ (bg)         │  │ (one-shot)   │               │
│  └──────────────┘  └──────────────┘  └──────────────┘               │
│                                                                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐                       │
│  │RAG API   │  │Eval Worker│  │RAG Migrate   │                       │
│  │ :8001     │  │ (bg)      │  │ (one-shot)   │                       │
│  └──────────┘  └──────────┘  └──────────────┘                       │
└─────────────────────────────────────────────────────────────────────┘
```

### 1. API Server (`apps/api/main.py`)
- FastAPI app on port 8000 (mapped to 8007 externally)
- Routes: uploads, files, directories, pipelines, sources
- API key authentication via `verify_api_key` dependency
- CORS open for dev (all origins)

### 2. Main Worker (`apps/worker/main.py`)
- Single async loop polling **three Redis queues**:
  - `file_manager:jobs` — file upload sync jobs
  - `ingestion:pipeline:jobs` — pipeline run jobs (index to Qdrant)
  - `ingestion:sync:jobs` — pipeline file sync jobs (reconcile indexed files)
- Also runs **APScheduler** for cron-based periodic syncs
- Cron trigger fields configurable via `SYNC_CRON_*` env vars (default: every 10 min)

### 3. Pathway Worker (`apps/pathway_worker/main.py`)
- Dedicated worker for **Airbyte connector syncs**
- Polls `pathway:sync:jobs` Redis queue
- Calls the external Pathway service via HTTP to run connectors
- Writes connector output to per-source MinIO buckets
- Updates source status in DB (syncing → connected/error)
- Triggers pipeline re-indexing for linked pipelines

### 4. Migrate (`src/shared/db/migrate.py`)
- Runs Alembic migrations on startup
- Retries up to 30 times (for DB startup race)

---

## Data Models (`src/shared/db/models.py`)

### Directory
```sql
directories (id UUID PK, name VARCHAR UNIQUE, created_at TIMESTAMPTZ)
```

### FileRecord
```sql
files (
  id UUID PK,
  directory_id UUID FK → directories,
  original_name VARCHAR(512),
  stored_name VARCHAR(512),
  relative_path VARCHAR(1024),
  mime_type VARCHAR(128),
  size_bytes INTEGER,
  content_hash VARCHAR(64),          -- SHA-256 of content
  client_content_hash VARCHAR(64),   -- client-supplied for dedup
  hash_verified BOOLEAN,
  duplicate_of_file_id UUID FK → files (self),
  status ENUM(processing|synced|failed|deleted|duplicate),
  error_message TEXT,
  created_at, updated_at TIMESTAMPTZ
)
```

### SyncJob
```sql
sync_jobs (
  id UUID PK,
  directory_id UUID FK → directories,
  file_id UUID FK → files,
  operation ENUM(upload|append|rename|delete),
  payload JSONB,
  status ENUM(pending|processing|success|failed),
  error_message TEXT,
  created_at, completed_at TIMESTAMPTZ
)
```

### Source
```sql
sources (
  id UUID PK,
  name VARCHAR(128) UNIQUE,
  connector_type VARCHAR(64),     -- google_drive, gcs, s3, confluence, etc.
  config JSONB,                    -- connector-specific config
  monitor_mode ENUM(live|scheduled),
  minio_bucket VARCHAR(256) UNIQUE, -- auto-generated from name + short UUID
  sync_interval_minutes INTEGER?,
  enabled BOOLEAN default true,
  last_sync_at TIMESTAMPTZ?,
  status VARCHAR(32) default 'disconnected',  -- disconnected|syncing|connected|error
  error_message TEXT?,
  created_at, updated_at TIMESTAMPTZ
)
```
Each source gets its own MinIO bucket (`{prefix}-{name}-{short_id}`).

### Pipeline
```sql
pipelines (
  id UUID PK,
  name VARCHAR(128) UNIQUE,
  description VARCHAR(512) UNIQUE,   -- human-readable, used by chat UI to select
  rag_strategy ENUM(naive|sparse|hybrid|multimodal|metadata),
  embedding_model VARCHAR(128),
  sparse_embedding_model VARCHAR(128)?,
  modality ENUM(text|image)?,
  directory_names JSONB,             -- which directories to index
  chunk_size INT default 1000,
  chunk_overlap INT default 120,
  qdrant_collection VARCHAR(128) UNIQUE,
  web_scraper_enabled BOOLEAN,
  scraper_seed_url VARCHAR(2048)?,
  scraper_max_depth INT default 2,
  scraper_max_pages INT default 50,
  scraper_mode VARCHAR(32) default 'httpx',
  created_at, updated_at TIMESTAMPTZ
)
```

### PipelineSource (M2M join)
```sql
pipeline_sources (
  id UUID PK,
  pipeline_id UUID FK → pipelines (CASCADE),
  source_id UUID FK → sources (CASCADE),
  UNIQUE(pipeline_id, source_id)
)
```
Links sources to pipelines. When a source syncs, all linked pipelines get re-indexed.

### PipelineRun
```sql
pipeline_runs (
  id UUID PK,
  pipeline_id UUID FK → pipelines,
  status ENUM(pending|processing|success|failed),
  files_total INT, files_processed INT,
  pages_indexed INT, points_upserted INT,
  scraper_crawl_job_id VARCHAR(64)?,
  scraper_scrape_job_id VARCHAR(64)?,
  error_message TEXT?,
  started_at, completed_at, created_at TIMESTAMPTZ
)
```

### IndexedFile
```sql
indexed_files (
  id UUID PK,
  pipeline_id UUID FK → pipelines (CASCADE),
  file_id UUID FK → files (CASCADE),
  content_hash VARCHAR(64),
  UNIQUE(pipeline_id, content_hash),
  INDEX(pipeline_id, file_id)
)
```
Tracks which files have been indexed per pipeline. Used by the sync runner to detect new/changed/deleted files.

### ChunkUpload
```sql
chunk_uploads (
  id UUID PK,
  directory_name VARCHAR(64),
  file_name VARCHAR(512),
  total_chunks INT, total_size INT,
  received_chunks JSONB,  -- list of chunk indices received
  mime_type VARCHAR(128)?,
  client_content_hash VARCHAR(64)?,
  target_file_id UUID FK → files?,
  operation ENUM(upload|append|rename|delete),
  created_at TIMESTAMPTZ
)
```

---

## API Endpoints

### Sources (`/api/sources`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/sources/connectors` | List available connector types |
| GET | `/api/sources` | List all sources |
| POST | `/api/sources` | Create source (creates MinIO bucket, triggers initial sync) |
| GET | `/api/sources/{id}` | Get source details |
| PATCH | `/api/sources/{id}` | Update source |
| DELETE | `/api/sources/{id}` | Delete source (removes MinIO bucket) |
| POST | `/api/sources/{id}/pipeline/{pipeline_id}` | Link source to pipeline |
| DELETE | `/api/sources/{id}/pipeline/{pipeline_id}` | Unlink source from pipeline |
| GET | `/api/sources/{id}/files` | List files in source's MinIO bucket |
| POST | `/api/sources/{id}/sync` | Manually trigger source sync |

### Pipelines (`/api/pipelines`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/pipelines/options` | Available RAG strategies, models, scraper modes |
| GET | `/api/pipelines/catalog` | Lightweight list for chat UI |
| GET | `/api/pipelines/by-description` | Lookup pipeline by description |
| GET | `/api/pipelines` | List all pipelines |
| POST | `/api/pipelines` | Create pipeline |
| GET | `/api/pipelines/runs` | All runs across all pipelines |
| GET | `/api/pipelines/runs/{id}` | Single run detail |
| GET | `/api/pipelines/{id}` | Get pipeline |
| PATCH | `/api/pipelines/{id}` | Update pipeline |
| GET | `/api/pipelines/{id}/stats` | Indexed files count + scraped pages |
| POST | `/api/pipelines/{id}/run` | Start a pipeline run (index to Qdrant) |
| GET | `/api/pipelines/{id}/runs` | Runs for this pipeline |
| POST | `/api/pipelines/{id}/sync` | Trigger file-sync for pipeline |
| GET | `/api/pipelines/{id}/sync-status` | Latest sync run status |
| POST | `/api/pipelines/query` | RAG search across indexed chunks |

### Other
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/api/upload` | File upload (chunked) |
| *(and related file/directory CRUD routes)* | | |

---

## Redis Queue Channels

| Queue Key | Producer | Consumer | Payload |
|-----------|----------|----------|---------|
| `file_manager:jobs` | API upload | Worker | `{"job_id": "..."}` |
| `ingestion:pipeline:jobs` | API pipeline run | Worker | `{"run_id": "..."}` |
| `ingestion:sync:jobs` | API sync / Pathway worker sync trigger | Worker | `{"pipeline_id": "..."}` |
| `pathway:sync:jobs` | API source sync / cron source sync | Pathway Worker | `{"source_id": "..."}` |

---

## MinIO Bucket Layout

- Per-directory: `{prefix}-{directory_name}` (for uploaded files)
- Per-source: `{prefix}-{name}-{short_uuid}` (for connector data)
- Prefix defaults to `source`

---

## Worker Processes

### Main Worker (`apps/worker/main.py`)
- **3 queues** in one loop, with 2s BRPOP timeout per queue
- Queue priority: file_manager:jobs > pipeline:jobs > sync:jobs
- **APScheduler** started alongside for cron triggers
- Cron fires every 10 minutes by default (`SYNC_CRON_MINUTE=*/10`)

### Pathway Worker (`apps/pathway_worker/main.py`)
- Single queue (`pathway:sync:jobs`) with 2s BRPOP timeout
- Each job calls external Pathway service → `POST /pathway/sync-source`
- Pathway runs Airbyte connector → streams output to per-source MinIO bucket

---

## Source Sync Flow

```
User creates source (POST /api/sources)
  │
  ├─ Create Source row in DB
  ├─ Create MinIO bucket (best-effort)
  ├─ enqueue_pathway_sync(source_id)
  │
  ▼
Pathway Worker
  ├─ dequeue_pathway_sync()
  ├─ sync_source_from_pathway(db, source_id)
  │   ├─ source.status = "syncing"
  │   ├─ POST /pathway/sync-source → external Pathway service
  │   │   ├─ Airbyte connector runs
  │   │   └─ Output lands in source's MinIO bucket
  │   ├─ source.status = "connected" (or "error")
  │   ├─ source.last_sync_at = now
  │   └─ _trigger_pipeline_syncs()
  │       └─ enqueue_sync_run(pipeline_id) for each linked pipeline
  │
  ▼
Main Worker (picks up sync:jobs)
  └─ sync_pipeline(db, pipeline_id)
      ├─ Compare IndexedFile records vs current files
      ├─ Index new files → embed → upsert to Qdrant
      ├─ Re-index changed files
      └─ Delete Qdrant chunks for removed files
```

### Cron-based sync (APScheduler)
- `sync_all_enabled_sources()` — triggers pathway sync for all enabled sources
- `sync_all_pipelines()` — runs sync_pipeline for every pipeline
- Both use the same CronTrigger, defaulting to every 10 minutes

---

## Pipeline Run Flow

```
POST /api/pipelines/{id}/run
  │
  ├─ Create PipelineRun (status=pending)
  ├─ enqueue_pipeline_run(run_id)
  │
  ▼
Worker (picks up pipeline:jobs)
  └─ run_pipeline_job(db, run_id)
      ├─ validate_pipeline_config()
      ├─ If web_scraper_enabled:
      │   └─ start_crawl_scrape_pipeline() via external scraper API
      ├─ Load SYNCED files from configured directories
      ├─ Skip already-indexed hashes
      ├─ For each new file:
      │   ├─ Download from MinIO to temp file
      │   ├─ iter_file_pages() → yield pages (text via PyMuPDF)
      │   ├─ chunk_text() → split into chunks
      │   ├─ embed_passage() / embed_image_png()
      │   ├─ upsert_batch() to Qdrant
      │   └─ Create IndexedFile record
      └─ run.status = success (or failed)
```

---

## RAG Indexing Details

### Chunking (`src/ingestion_service/utils/text_splitter.py`)
- Configurable `chunk_size` and `chunk_overlap` per pipeline
- Text extracted from PDF (via PyMuPDF) page by page
- Each page yields `FilePage(text, image_png?, page_index)`

### Embedding (`src/ingestion_service/embeddings/client.py`)
- Uses LiteLLM proxy at `litellm_base_url` for model routing
- Text: `embed_passage(chunk)` → dense vector
- Image: `embed_image_png(png_bytes)` → dense vector
- Sparse: `fastembed` (e.g., `Qdrant/bm25`)

### Qdrant Storage (`src/ingestion_service/vector/qdrant_store.py`)
- One collection per pipeline (name defined at creation)
- Collections created on first write with correct dimensionality
- Supports dense + sparse vectors for hybrid search

### Sync Runner (`sync_runner.py`) vs Pipeline Runner (`pipeline_runner.py`)
- **sync_runner.py**: Idempotent, compares IndexedFile tracking records against current SYNCED files on disk. Only indexes new/changed files, removes Qdrant points for deleted files. Used by cron and post-source-sync triggers.
- **pipeline_runner.py**: Full run, skips already-indexed hashes. Supports web scraper pipelines.

---

## Configuration (`src/shared/config/settings.py`)

Key environment variables (loaded from `.env`):

| Variable | Default | Description |
|----------|---------|-------------|
| `database_url` | `postgresql://ingestion:ingestion@localhost:5432/ingestion` | Postgres connection |
| `redis_url` | `redis://localhost:6379/0` | Redis connection |
| `pathway_queue` | `pathway:sync:jobs` | Redis queue key for pathway syncs |
| `minio_endpoint` | `minio:9000` | MinIO endpoint |
| `minio_access_key` | `minioadmin` | MinIO access key |
| `minio_secret_key` | `minioadmin` | MinIO secret key |
| `minio_bucket_prefix` | `source` | Prefix for all MinIO buckets |
| `qdrant_url` | `http://localhost:6333` | Qdrant vector DB |
| `qdrant_api_key` | `qdrant` | Qdrant API key |
| `litellm_base_url` | `http://host.docker.internal:4000` | LiteLLM proxy for embedding |
| `openai_api_key` | `sk-bot` | API key for LiteLLM |
| `scraper_api_url` | `http://localhost:8000` | Web scraper API (external service) |
| `SYNC_CRON_MINUTE` | `*/10` | Cron schedule for periodic syncs |

---

## Docker Compose Services

From `docker-compose.yaml`:

| Service | Image/Build | Port | Command |
|---------|-------------|------|---------|
| `api` | ingestion-backend/Dockerfile | 8007:8000 | uvicorn apps.api.main:app |
| `worker` | ingestion-backend/Dockerfile | — | python -m apps.worker.main |
| `pathway-worker` | ingestion-backend/Dockerfile | — | python -m apps.pathway_worker.main |
| `migrate` | ingestion-backend/Dockerfile | — | python -m src.shared.db.migrate |
| `web` | ingestion-frontend/Dockerfile | 5173:5173 | (frontend dev server) |
| `scraper-api` | tharun0511/web-scrapper-wokspace | 8000:8000 | uvicorn |
| `scraper-worker` | tharun0511/web-scrapper-wokspace | — | background worker |
| `scraper-migrate` | tharun0511/web-scrapper-wokspace | — | crawler-db-migrate |
| `postgres` | postgres:16-alpine | 5433:5432 | (database) |
| `redis` | redis:7-alpine | 6379:6379 | (cache/queue) |
| `minio` | minio/minio | 9000+9001 | S3-compatible storage |
| `qdrant` | qdrant/qdrant:v1.18.0 | 6333:6333 | vector database |
| `otel-collector` | otel/opentelemetry-collector | 4317+4318 | OpenTelemetry |
| `rag-api` | rag-app-workspace/Dockerfile | 8001:8001 | RAG query API |
| `eval-worker` | rag-app-workspace/Dockerfile | — | evaluation worker |
| `rag-migrate` | rag-app-workspace/Dockerfile | — | RAG DB migrations |

---

## Project Structure

```
ingestion-backend/
├── apps/
│   ├── api/
│   │   ├── main.py                 # FastAPI app
│   │   ├── exceptions.py           # Error handlers
│   │   └── routes/
│   │       ├── directories.py      # Directory CRUD
│   │       ├── files.py            # File CRUD
│   │       ├── pipelines.py        # Pipeline + RAG query + run
│   │       ├── sources.py          # External source CRUD
│   │       └── uploads.py          # Chunked file upload
│   ├── pathway_worker/
│   │   └── main.py                 # Pathway Airbyte worker loop
│   └── worker/
│       ├── main.py                 # Main async worker loop
│       └── scheduler.py            # APScheduler cron definitions
├── scripts/
│   ├── run-api.sh
│   ├── run-worker.sh
│   ├── run-pathway-worker.sh
│   └── run-migrate.sh
├── src/
│   ├── file_manager/
│   │   └── core/
│   │       ├── operations.py       # File sync job execution
│   │       ├── storage.py          # Local storage helpers
│   │       ├── validator.py        # File type validation
│   │       ├── chunks.py           # Chunk reassembly
│   │       ├── duplicates.py       # Content hash dedup
│   │       └── service.py          # File manager orchestration
│   ├── ingestion_service/
│   │   ├── clients/
│   │   │   ├── scraper.py          # Web scraper API client
│   │   │   └── source_sync.py      # Source sync trigger client
│   │   ├── core/
│   │   │   ├── pathway_sync.py     # Airbyte/Pathway sync orchestration
│   │   │   ├── pipeline_runner.py  # Full pipeline run (index to Qdrant)
│   │   │   ├── sync_runner.py      # Idempotent file-sync (diff-based)
│   │   │   ├── indexer.py         # FileIndexer: chunk + embed + upsert
│   │   │   └── page_yielder.py    # PDF page extraction (PyMuPDF)
│   │   ├── embeddings/
│   │   │   ├── client.py          # Dense embedding client (LiteLLM)
│   │   │   └── sparse_client.py   # Sparse embedding (fastembed)
│   │   ├── vector/
│   │   │   ├── qdrant_store.py    # Qdrant vector store operations
│   │   │   ├── search.py          # RAG search (hybrid/dense/sparse)
│   │   │   ├── filters.py         # Metadata filter building
│   │   │   └── hit_mapper.py      # Search result mapper
│   │   ├── utils/
│   │   │   ├── text_splitter.py   # Chunk text by size/overlap
│   │   │   └── validation.py      # Input validation
│   │   └── types.py               # Shared type constants
│   └── shared/
│       ├── config/
│       │   └── settings.py        # Pydantic Settings
│       ├── db/
│       │   ├── models.py           # All SQLAlchemy models
│       │   ├── session.py          # Async engine + session factory
│       │   └── migrate.py          # Alembic migration runner
│       ├── io/
│       │   └── async_files.py      # Async file I/O helpers
│       ├── queue/
│       │   └── client.py           # Redis queue enqueue/dequeue
│       ├── storage/
│       │   ├── __init__.py         # Public API re-exports
│       │   └── s3_client.py        # MinIO/S3 async client
│       └── auth.py                 # API key verification
├── alembic/
│   └── versions/                   # Migration scripts
│       ├── 001_initial_schema.py
│       ├── 002_pipelines.py
│       ├── 003_pipeline_description.py
│       ├── 004_indexed_files.py
│       └── 005_sources.py
├── pyproject.toml
├── alembic.ini
├── Dockerfile
└── ARCHITECTURE.md
```

---

## Key Design Decisions

1. **Dual worker architecture**: Main worker handles file/pipeline operations; pathway worker handles connector syncs. Separated because connector syncs are I/O-heavy and long-running (up to 5 min HTTP timeouts).

2. **Idempotent sync runner**: `sync_runner.py` compares `IndexedFile` tracking records (by content_hash) against current SYNCED files. Only processes differences. Safe to run on cron without duplicating work.

3. **Per-source MinIO buckets**: Each source gets its own bucket. Bucket name is deterministic from source name + UUID prefix. The Pathway worker writes directly to these buckets.

4. **Fire-and-forget on creation**: Source creation triggers bucket creation and initial sync as fire-and-forget tasks. Failures are non-fatal (will retry on next cron tick).

5. **External Pathway service**: The Pathway Airbyte integration runs as an external HTTP service (not in-process). The backend calls `POST {scraper_api_url}/pathway/sync-source` to trigger connector runs.

6. **APScheduler in worker process**: The cron scheduler lives inside the main worker process (not as a separate service). It uses `AsyncIOScheduler` with configurable `CronTrigger` fields.
