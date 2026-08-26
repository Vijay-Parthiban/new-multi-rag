# Multi-RAG Ingestion Platform & Stream Processing Pipeline

Comprehensive document upload, Airbyte connector stream ingestion, and file management platform powered by Pathway CDC, FastAPI, React, MinIO object storage, and Qdrant vector database.

> 📘 **Full Architecture & Environment Replication Guide**: See [`PROJECT_IMPLEMENTATION_AND_STATE.md`](../PROJECT_IMPLEMENTATION_AND_STATE.md) for step-by-step instructions on replicating and deploying the complete project in any environment.


## 1. Quick Start

```bash
# Clone and navigate to workspace
cd ingestion-workspace

# Build and launch all 12 Docker containers
docker compose up -d --build
```

### Microservice Endpoints & Services

| Service | Internal Port | External Host Port | Public / Local URL |
| :--- | :--- | :--- | :--- |
| **Frontend UI (Vite + React)** | 5173 | **5173** | `http://localhost:5173` / `https://semiwildly-superadaptable-vernice.ngrok-free.dev` |
| **Ingestion Backend API** | 8000 | **8007** | `http://localhost:8007` |
| **RAG Query API** | 8001 | **8001** | `http://localhost:8001` |
| **Web Scraper API** | 8000 | **8000** | `http://localhost:8000` |
| **Qdrant Vector Database** | 6333 | **6333** | `http://localhost:6333/dashboard` |
| **MinIO Console & Storage** | 9000 / 9001 | **9000 / 9001** | `http://localhost:9001` (`minioadmin` / `minioadmin`) |
| **PostgreSQL Database** | 5432 | **5433** | `localhost:5433` (`ingestion` + `crawler` DBs) |
| **Redis Cache & Queue** | 6379 | **6379** | `localhost:6379` |
| **ngrok Tunnel Agent** | 4040 | **4040** | `http://localhost:4040` |


## 2. Core Architecture Highlights

- **Pathway CDC Engine (`pw.io.airbyte.read`)**: Processes real-time Change Data Capture streams from 12+ Airbyte connectors with dynamic tuple retractions (`+1` additions, `-1/+1` updates, `-1` retractions).
- **Sub-5-Second Live Synchronization**: Background live poller (`poll_interval_seconds=3`) hooked directly into FastAPI `lifespan` application lifecycle (`apps/api/main.py`).
- **Differential State Sync & Storage Isolation**: Automatic file additions, updates/replaces, and deletions mirrored directly to source-isolated MinIO object storage buckets (`connectors/{connector_id}/...`).
- **Native Dark Premium UI**: React 18 + Vite frontend with native CSS variable styling, glassmorphism visual design, zero Tailwind dependencies, and host-proxied API requests.
- **High Performance & Optimization**: DB connection pool size set to **30** (+50 overflow), SQL eager loading (`selectinload`), and API response memoization achieving **< 80 ms** page loads and **~500 ms** client-side navigation.
```
Browser (React)
    │
    ▼
FastAPI (async) ──► Postgres (metadata)
    │                    ▲
    ├── chunk staging    │
    └── enqueue job ──► Redis queue ──► Worker (async)
                              │
                              └── move files to disk storage
```

**Upload flow**

1. Client computes SHA-256 and calls `POST /api/uploads/init`.
2. Client sends chunks via `PUT /api/uploads/{id}/chunks/{n}` (multipart field `chunk`).
3. Client calls `POST /api/uploads/{id}/complete` — server stitches, verifies hash, checks duplicates, creates DB record, enqueues sync job.
4. Worker moves staged file to `storage/uploads/{directory}/` and sets status to `synced`.

**Duplicates** are recorded in the database only (status `duplicate`) — no disk write, no worker job. Other uploads in the same batch continue.

---

# Backend (`ingestion-backend`)

Python 3.11 · FastAPI · async SQLAlchemy · asyncpg · Alembic · Redis · `filetype` (pure Python, no libmagic)

## Services

| Process | Entry point | Role |
|---------|-------------|------|
| **API** | `apps.api.main:app` | HTTP routes, chunk intake (migrations run via `migrate` service) |
| **Worker** | `apps.worker.main` | Consumes Redis queue, syncs files to disk |

## Project layout

```
ingestion-backend/
├── apps/
│   ├── api/
│   │   ├── main.py              # FastAPI app, CORS, lifespan
│   │   ├── exceptions.py        # AppError → JSON handler
│   │   └── routes/
│   │       ├── uploads.py       # Chunked upload
│   │       ├── directories.py   # List dirs / files
│   │       └── files.py         # CRUD, view, append
│   └── worker/
│       └── main.py              # Async job loop
├── alembic/                     # DB migrations
├── alembic.ini
├── src/
│   ├── file_manager/
│   │   ├── core/
│   │   │   ├── chunks.py        # Init / save / stitch chunks
│   │   │   ├── service.py       # Complete upload logic
│   │   │   ├── storage.py       # Jobs, directories
│   │   │   ├── operations.py    # Worker: upload/append/rename/delete
│   │   │   ├── duplicates.py    # Per-directory SHA-256 duplicate check
│   │   │   ├── validator.py     # Filename + filetype validation
│   │   │   └── errors.py        # AppError hierarchy
│   │   └── utils/
│   │       ├── paths.py         # Storage paths, sanitization
│   │       └── hashing.py       # SHA-256 verify
│   └── shared/
│       ├── config/settings.py   # Env-based settings
│       ├── db/
│       │   ├── models.py        # SQLAlchemy models
│       │   ├── session.py       # AsyncSession factory
│       │   └── migrate.py       # Alembic upgrade (with retry)
│       ├── io/async_files.py    # Async disk I/O via thread pool
│       └── queue/client.py      # Async Redis enqueue/dequeue
├── Dockerfile
└── pyproject.toml
```

## Storage layout (Docker volume `file_storage`)

```
storage/
├── temp/{upload_id}/       # Chunk parts (cleaned on complete)
├── staging/{job_id}/       # Stitched file before worker move
└── uploads/{directory}/    # Final synced files
```

## Database models

| Table | Purpose |
|-------|---------|
| `directories` | Named folders (user-chosen at upload) |
| `files` | File metadata, hash, status, duplicate link |
| `sync_jobs` | Background jobs (upload, append, rename, delete) |
| `chunk_uploads` | In-progress chunked upload sessions |

**File statuses:** `processing` · `synced` · `failed` · `deleted` · `duplicate`

**Job operations:** `upload` · `append` · `rename` · `delete`

Migrations run automatically when the API starts (`alembic upgrade head`). Initial revision: `001_initial`.

## API reference

Base URL: `http://localhost:8007`

### Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | `{ "status": "ok" }` |

### Uploads

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| POST | `/api/uploads/init` | 201 | Start chunked upload |
| PUT | `/api/uploads/{upload_id}/chunks/{chunk_index}` | 204 | Upload one chunk (multipart `chunk`) |
| POST | `/api/uploads/{upload_id}/complete` | 202 | Stitch, verify hash, enqueue sync |

**Init body:** `directory_name`, `file_name`, `total_chunks`, `total_size`, `client_content_hash` (required SHA-256 hex), optional `mime_type`.

### Directories

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/directories` | List all folders |
| GET | `/api/directories/{name}/files` | List files in folder (excludes deleted) |

### Files

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| GET | `/api/files/{file_id}` | 200 | File metadata |
| GET | `/api/files/{file_id}/view` | 200 | Inline file preview (`FileResponse`) |
| PATCH | `/api/files/{file_id}` | 202 | Rename (async job) — body: `{ "new_name" }` |
| DELETE | `/api/files/{file_id}` | 202 | Delete (async job) |
| POST | `/api/files/{file_id}/append/init` | 201 | Start append upload |
| POST | `/api/files/{file_id}/append/{upload_id}/complete` | 202 | Complete append |

### Errors

Structured JSON:

```json
{
  "error": {
    "code": "DUPLICATE_FILE",
    "message": "Human-readable message",
    "details": {}
  }
}
```

Common codes: `VALIDATION_ERROR`, `NOT_FOUND`, `CONFLICT`, `CORRUPTION_DETECTED`, `DUPLICATE_FILE`, `FILE_TYPE_BLOCKED`.

## Environment variables

| Variable | Default (local) | Description |
|----------|-----------------|-------------|
| `DATABASE_URL` | `postgresql://ingestion:ingestion@postgres:5432/ingestion` | Sync URL; auto-converted to `postgresql+asyncpg://` |
| `REDIS_URL` | `redis://redis:6379/0` | Job queue |
| `STORAGE_PATH` | `/app/storage` | File storage root |
| `FILE_MANAGER_QUEUE` | `file_manager:jobs` | File sync queue |
| `PIPELINE_QUEUE` | `ingestion:pipeline:jobs` | Pipeline indexing queue |
| `QDRANT_URL` | `http://qdrant:6333` | Shared vector store |
| `QDRANT_COLLECTION` | `scrape_embeddings` | Same collection as web-scrapper |
| `LITELLM_BASE_URL` | LiteLLM proxy URL | Dense + multimodal embeddings |
| `SCRAPER_API_URL` | `http://scraper-api:8000` | Web-scrapper API (same compose network) |

## Dependencies

```
fastapi, uvicorn, sqlalchemy[asyncio], asyncpg, alembic, redis, pydantic-settings,
filetype, qdrant-client, openai, fastembed, httpx, pymupdf
```

## Features implemented

- Chunked upload with client + server SHA-256 verification
- User-chosen directory (folder) per upload
- Duplicate detection per directory (SHA-256)
- Async background sync via Redis + worker
- File operations: rename, delete, append (API ready)
- **RAG pipelines** — per-pipeline Qdrant collection, embedding models, and unique description for chat selection
- Pipeline strategies: naive, sparse, hybrid, multimodal, metadata
- Page-yielding PDF indexing (RAM-safe) with text chunking or image base64 embed
- Web scraper integration passes collection + models to web-scrapper `POST /pipelines/crawl-scrape`

## Pipeline API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/pipelines/options` | RAG strategies, suggested models (not defaults) |
| GET | `/api/pipelines/catalog` | Lightweight list for chat UI (select by `description`) |
| GET | `/api/pipelines/by-description?description=...` | Lookup pipeline by unique description |
| GET/POST | `/api/pipelines` | List / create pipeline config |
| POST | `/api/pipelines/{id}/run` | Start indexing run (worker) |
| GET | `/api/pipelines/{id}/runs` | Run history + progress |

Each pipeline requires:
- **`description`** — unique human string used in chat UI instead of UUID
- **`qdrant_collection`** — unique collection name (web + file indexing share it)
- **`embedding_model`** — free-text LiteLLM model (swappable per pipeline)
- **`sparse_embedding_model`** — required for sparse/hybrid/metadata strategies

## Not yet built

- Orphan temp/staging cleanup job
- Append UI in frontend
- Auth / multi-tenant
- Non-PDF image modality for plain text files

---

# Frontend (`ingestion-frontend`)

React 19 · TypeScript · Vite 6 · React Router 7 · no UI framework (custom GitHub-inspired CSS)

## Project layout

```
ingestion-frontend/
├── src/
│   ├── App.tsx                  # Route definitions
│   ├── main.tsx                 # BrowserRouter entry
│   ├── api.ts                   # API client + chunked upload
│   ├── hash.ts                  # Client SHA-256 (Web Crypto)
│   ├── index.css                # Design system + layout
│   ├── components/
│   │   ├── AppLayout.tsx        # Sidebar shell + outlet
│   │   ├── PageHeader.tsx       # Title, breadcrumbs, actions
│   │   ├── Breadcrumb.tsx
│   │   ├── StatusBadge.tsx
│   │   └── Icons.tsx            # SVG icons (folder, file, etc.)
│   ├── pages/
│   │   ├── HomePage.tsx         # Overview + quick links
│   │   ├── BrowsePage.tsx       # Folder list (GitHub-style table)
│   │   ├── DirectoryPage.tsx    # Files in a folder + actions
│   │   ├── UploadPage.tsx       # Drag-and-drop chunked upload
│   │   ├── PipelinesPage.tsx    # RAG pipeline configuration + runs
│   │   └── FileViewerPage.tsx   # Split-pane preview (iframe)
│   └── utils/format.ts          # Size + relative time helpers
├── Dockerfile
├── package.json
└── vite.config.ts
```

## Routes

| Path | Page | Description |
|------|------|-------------|
| `/` | Overview | Dashboard, recent folders, links to upload/browse |
| `/upload` | Upload | Pick folder name, drag-and-drop files, batch upload |
| `/browse` | Folders | All directories in a table |
| `/browse/:name` | Folder | Files with status, rename, delete, view links |
| `/browse/:name/view/:fileId` | Viewer | Sidebar file list + iframe preview |
| `/pipelines` | Pipelines | RAG config, folder selection, web scraper, run history |

**Legacy redirects:** `/directories/*` → `/browse/*`

## UI structure

- **Sidebar navigation** — Overview, Folders, Upload, Pipelines
- **GitHub-style file browser** — bordered panels, folder/file icons, monospace names, hover rows
- **Breadcrumbs** on all pages
- **Auto-refresh** — folder and file lists poll every 4–5 seconds for sync status updates

## Upload behavior (frontend)

1. Computes SHA-256 before upload (`hash.ts`).
2. Sends 5 MB chunks (configurable via `CHUNK_SIZE` in `api.ts`).
3. Blocks video/audio extensions client-side.
4. Handles duplicates and `CORRUPTION_DETECTED` per file without stopping the batch.
5. Redirects to `/browse/{directory}` after upload.

## Environment

| Variable | Description |
|----------|-------------|
| `VITE_API_URL` | API base URL (browser must reach host) — default `http://localhost:8007` |

Set in `docker-compose.yaml` for the `web` service.

## Scripts

```bash
npm install
npm run dev      # local dev server
npm run build    # production build → dist/
```

## Features implemented

- Chunked upload with hash verification
- Folder browser (GitHub-style tables)
- File preview in iframe for synced files
- Duplicate badge + link to original
- Rename / delete from folder view
- **Pipeline configuration UI** — RAG strategy, embedding model, folder multi-select, scraper toggle
- Responsive sidebar (collapses on mobile)

## Not yet built

- Append file UI (backend API exists)
- Settings page
- Auth, search, pagination

---

# Docker Compose

| Service | Image / build | Port |
|---------|---------------|------|
| `api` | `ingestion-backend` | 8007 → 8000 |
| `worker` | `ingestion-backend` | — |
| `web` | `ingestion-frontend` | 5173 |
| `postgres` | postgres:16-alpine | 5432 |
| `redis` | redis:7-alpine | 6379 |

Shared volume `file_storage` mounted at `/app/storage` on API and worker. Postgres has a healthcheck; API and worker wait for it before starting.

---

# Development notes

**Schema changes:** add a revision in `ingestion-backend/alembic/versions/`, then run migrations:

```bash
docker compose run --rm migrate
# or locally: python -m src.shared.db.migrate
```

**Autogenerate (from backend dir with DB running):**

```bash
alembic revision --autogenerate -m "description"
```

**Chunk upload from curl:** chunks must be sent as `multipart/form-data` with field name `chunk`, not raw body.
