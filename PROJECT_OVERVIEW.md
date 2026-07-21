# RAG Full Pipeline — Project Overview

**Last reviewed:** 2026-07-21

This repository is a **loose monorepo** of three independently packaged products that together form an end-to-end RAG (Retrieval-Augmented Generation) platform: ingest documents and web content → embed into Qdrant → retrieve / rerank / generate → evaluate.

There is **no root shared Python package historically**. As of 2026-07-21, shared Qdrant/auth primitives live in `shared-libs/platform-common/` and are re-exported from each workspace. Remaining integration is still Docker, HTTP APIs, environment contracts, and the shared Qdrant payload schema.

---

## Top-level layout

```text
rag-full-pipeline/
├── PROJECT_OVERVIEW.md          ← this file
├── CODE_ANALYSIS.md             ← bugs, security, reuse plan
├── shared-libs/
│   └── platform-common/         ← shared auth + Qdrant helpers
├── ingestion-workspace/         ← upload UI + file indexing + orchestration
│   ├── proxy/                   ← nginx reverse proxy (Docker + config)
│   └── postgres-init/           ← custom Postgres init (Dockerfile + init.sql)
├── web-scrapper-workspace/      ← crawl → scrape → embed → Qdrant write
└── rag-app-workspace/           ← retrieve → rerank → generate → eval
```

| Workspace | Role | Default ports | External access |
|-----------|------|---------------|-----------------|
| **ingestion-workspace** | Document upload, pipeline config, file→Qdrant indexing, end-to-end UI | Frontend `5173`, API `8007`, Proxy `8090` | Via proxy at `:8090` or ngrok |
| **web-scrapper-workspace** | Web crawl/scrape, embeddings, shared infra (Postgres/Redis/Qdrant) | API `8000` | Via proxy at `/scraper-api/` |
| **rag-app-workspace** | RAG API + eval worker (reads Qdrant) | API `8001` | Via proxy at `/rag-api/` |

---

## System architecture

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│                            ngrok-free.dev (TLS)                                  │
│     https://semiwildly-superadaptable-vernice.ngrok-free.dev                     │
└───────────────────────────┬──────────────────────────────────────────────────────┘
                            │
                     ┌──────▼──────┐
                     │  nginx Proxy │  :8090
                     │  single port │
                     └──┬───┬───┬──┘
                        │   │   │
              ┌─────────┘   │   └──────────┐
              ▼             ▼               ▼
     ingestion-frontend  Scraper API     RAG API
     (React/Vite :5173)   (:8000)         (:8001)
              │                              │
              ▼                              ▼
       Ingestion API                    Rag DB (Postgres)
         (:8007)                        `rag` DB
              │
         ┌────┴────┐
         │         │
    File Indexer  Pipeline
     (worker)    (worker)
         │         │
         └────┬────┘
              │
              ▼
         ┌──────────┐
         │  Qdrant   │ :6333
         │  scrape_  │
         │ embeddings│
         └─────┬─────┘
               │
         ┌─────▼──────┐
         │  LiteLLM    │ host.docker.internal:4000
         │  (embeds,   │
         │   chat,     │
         │   rerank)   │
         └────────────┘

 Infrastructure (Docker Compose — shared across all services):
   ┌──────────┐  ┌──────────┐  ┌──────────────────────┐
   │ Postgres  │  │  Redis   │  │ Custom Postgres Init │
   │ 16-alpine │  │ 7-alpine │  │ (bakes DB/user init) │
   │ 3 DBs:    │  │ 3 queues │  └──────────────────────┘
   │ ingestion │  │ (scraper │
   │ crawler   │  │  eval,   │
   │ rag       │  │  ingest) │
   └──────────┘  └──────────┘
```

### Data flow (happy path)

1. **Files:** User uploads via UI → chunked upload API → worker syncs to disk → pipeline/sync runner indexes PDFs/text → Qdrant points with `source_type=file_ingest`.
2. **Web:** Pipeline (or API) calls scraper `POST /pipelines/crawl-scrape` → BFS crawl → Playwright scrape → dense + BM25 sparse embed → Qdrant points with `source_type=web_scrape`.
3. **Chat:** UI/API `POST /chat` → retrieve from Qdrant → optional rerank → LLM generate → persist chat/trace in Postgres → optional async RAGAS metrics via RQ.

---

## Workspace details

### 1. `ingestion-workspace`

**Purpose:** Combined file-management platform and orchestration console for the full stack.

| Component | Path | Notes |
|-----------|------|-------|
| Backend API | `ingestion-backend/apps/api/` | FastAPI: uploads, directories, files, pipeline config, chat proxy |
| File manager | `ingestion-backend/src/file_manager/` | Chunked upload, hashing, duplicate detection, storage |
| Ingestion service | `ingestion-backend/src/ingestion_service/` | Pipeline/sync runners, indexer, Qdrant write |
| Shared | `ingestion-backend/src/shared/` | Settings, DB models/session, Redis, auth |
| Frontend | `ingestion-frontend/` | React pages for upload, browse, pipelines, tracking, chat, eval |
| **Proxy** | `proxy/` | **nginx reverse proxy** — routes `/api/*` → `api:8000`, `/scraper-api/*` → `scraper-api:8000`, `/rag-api/*` → `rag-api:8001`, `/*` → `web:5173` |
| **Postgres init** | `postgres-init/` | **Custom Postgres image** — bakes `init.sql` (creates `crawler` user + `crawler`/`rag` DBs) to work around WSL bind-mount bug |
| Compose | `docker-compose.yaml` | **Unified stack**: Postgres, Redis, Qdrant, scraper image, RAG build, ingestion, proxy |

**Key env (`.env` for ingestion, `.env.scraper` for scraper, `.env.rag` for RAG):**
`DATABASE_URL`, `REDIS_URL`, `STORAGE_PATH`, `QDRANT_*`, `LITELLM_BASE_URL`, `OPENAI_API_KEY`, `SCRAPER_API_URL`, `API_KEY`.

**Frontend env (Vite):** Uses **relative paths** (`/api/`, `/scraper-api/`, `/rag-api/`) so all API calls go through the same origin. This avoids CORS/same-origin issues when accessed via ngrok or any other domain.

**Queues:** `file_manager:jobs`, `ingestion:pipeline:jobs`, `ingestion:sync:jobs`.

---

### 2. `web-scrapper-workspace`

**Purpose:** Crawl sites once, scrape/index many times; write hybrid vectors into shared Qdrant. Also hosts shared Docker infra used in the split-stack topology.

| Component | Path | Notes |
|-----------|------|-------|
| API | `apps/api/` | Crawls, scrapes, pipeline, vector query |
| Worker | `apps/worker/` | RQ: crawl / scrape / page / finalize |
| CLI | `apps/cli/` | Typer CLI for crawl/scrape ops |
| crawler-core | `libs/crawler-core/` | BFS frontier, link extraction |
| scrapper-core | `libs/scrapper-core/` | Playwright scrape, embed, Qdrant upsert |
| crawler-db | `libs/database/` | Job models + Alembic |
| crawler-shared | `libs/shared/` | Settings, auth, Redis, Playwright helpers |

**Key env:** `DATABASE_URL`, `REDIS_URL`, `API_BASE_URL`, `QDRANT_*`, `LITELLM_*`, `EMBEDDING_MODEL`, `SPARSE_EMBEDDING_MODEL`, `API_KEY`, scrape concurrency/timeouts.

**Uses pre-built Docker image:** `tharun0511/web-scrapper-wokspace:latest` (note: typo "wokspace" in the image name).

**Docs:** `docs/PROJECT_EXPLAINED.md` (partially stale vs current Qdrant/auth code).

---

### 3. `rag-app-workspace`

**Purpose:** Read-only RAG over the shared Qdrant collection: retrieve → rerank → generate, plus golden-set evaluation.

| Component | Path | Notes |
|-----------|------|-------|
| rag-api | `apps/rag-api/` | FastAPI: search, chat, staged pipeline, eval management |
| eval-worker | `apps/eval-worker/` | RQ worker: chat metrics + golden runs |
| rag-core | `libs/rag-core/` | `RAGPipeline` orchestration |
| retrieval-core | `libs/retrieval-core/` | Thin retriever over vector-core |
| vector-core | `libs/vector-core/` | Qdrant read search, embeddings, sparse |
| reranker-core | `libs/reranker-core/` | LiteLLM `/v1/rerank` |
| generation-core | `libs/generation-core/` | Text / vision / fusion generation |
| eval-core | `libs/eval-core/` | RAGAS + IR metrics |
| rag-database | `libs/database/` | Chat traces, golden datasets, Alembic |
| rag-shared | `libs/shared/` | Settings, auth, chunk types |

**Key env:** `DATABASE_URL` (`postgresql+psycopg://crawler:crawler@postgres:5432/rag`), `REDIS_URL`, `QDRANT_*`, `LITELLM_*`, model names, `API_KEY`, RAGAS/eval flags.

---

## Shared contracts (the real cross-workspace API)

### Qdrant collection schema

- Collection name (default): `scrape_embeddings`
- Named vectors: `dense` (cosine), `sparse` (BM25 / FastEmbed, IDF modifier)
- Deterministic point IDs: `uuid5(NAMESPACE_URL, point_id)`

### Payload vocabulary

| Field | Meaning |
|-------|---------|
| `source_type` | `web_scrape` \| `file_ingest` |
| `source_id` | Job or document scope id |
| `source_locator` | URL or file path |
| `type` | `text` \| `image` |
| `content` | Chunk text or image data URI |
| `chunk_index` | Chunk order |
| `title`, `pipeline_id`, `pipeline_description` | Optional metadata |
| `scrape_job_id` | Present for web scrapes |

Embedding **model names and dimensions must match** across writer workspaces and the RAG reader. Dense/sparse clients and Qdrant helpers live in `shared-libs/platform-common`.

Crawl seed URLs are SSRF-checked (blocks private/loopback/metadata hosts). Set `ALLOW_PRIVATE_CRAWL_URLS=true` only for local/dev.

### HTTP integration points

| From → To | Endpoint / mechanism |
|-----------|----------------------|
| Ingestion backend → Scraper | `POST {SCRAPER_API_URL}/pipelines/crawl-scrape` |
| Frontend → Scraper | `/scraper-api/crawls`, `/scraper-api/scrapes` (through proxy) |
| Frontend → RAG | `/rag-api/chat`, sessions, metrics, evaluate (through proxy) |
| Frontend → Ingestion | `/api/...` (through proxy) |
| RAG → Qdrant | Direct client (no scraper HTTP for retrieval) |

---

## Runtime topologies

### A. Unified (recommended — currently active)

From `ingestion-workspace/`:

```bash
docker compose up --build -d
```

Owns:
- **Postgres** with custom init (3 databases: `ingestion`, `crawler`, `rag`)
- **Redis** for RQ queues (scraper, eval, ingestion)
- **Qdrant** v1.18 with API key `qdrant`
- **Scraper** (API + worker, pre-built image `tharun0511/web-scrapper-wokspace:latest`)
- **RAG** (API + eval-worker, built from source)
- **Ingestion** (migration, API, worker, web frontend)
- **nginx Proxy** (reverse proxy at `:8090` for same-origin API access)

```bash
# Build and start everything
docker compose build
docker compose up -d

# Update frontend (after code changes)
docker compose build web && docker compose up -d web proxy
```

**External dependency:** LiteLLM on the host at `:4000` (`host.docker.internal`).

### B. ngrok tunnel (external Web UI access)

```bash
# Start ngrok pointing to the nginx proxy through Docker's gateway IP
ngrok http 172.25.0.1:8090 \
  --url https://semiwildly-superadaptable-vernice.ngrok-free.dev \
  --log=stdout
```

The ngrok URL provides TLS-terminated access to the entire platform. All API calls use relative paths through the proxy, so they work identically on localhost and ngrok — **no CORS issues**.

**Current ngrok URL:** https://semiwildly-superadaptable-vernice.ngrok-free.dev

### C. Split stack

1. Start `web-scrapper-workspace` (infra + `rag-shared` network).
2. Create Postgres DB `rag`.
3. Start `rag-app-workspace` attached to external `rag-shared`.
4. Optionally run ingestion against those services.

---

## Docker configuration notes

### Custom Docker images

Two custom images were created to work around WSL / bind-mount limitations:

| Image | Dockerfile | Purpose |
|-------|------------|---------|
| `custom-postgres-init:latest` | `postgres-init/Dockerfile` | Bakes `init.sql` (creates `crawler` user, `crawler` + `rag` databases) directly into the Postgres image. Avoids WSL bind-mount bug where `.sql` files are treated as directories. |
| `ingestion-workspace-proxy` | `proxy/Dockerfile` | nginx:alpine with baked-in `nginx.conf` routing configuration. |

### Networks

- `rag-shared` — external Docker network connecting Postgres, Redis, Qdrant to RAG services. Created once with `docker network create rag-shared`.
- `default` — Compose internal network for all other service communication.

### Key modifications from original source

1. **Postgres image** — swapped `postgres:16-alpine` → `custom-postgres-init:latest` in docker-compose.yaml
2. **Nginx proxy service** — added to docker-compose.yaml (port `8090`)
3. **Frontend API URLs** — changed from `http://localhost:8007` / `8001` / `8000` to relative paths `""`, `/scraper-api`, `/rag-api` in both `api.ts` defaults and docker-compose VITE env vars
4. **Vite allowedHosts** — added ngrok domain to `vite.config.ts` to prevent host-header rejection
5. **psycopg** — added `psycopg[binary]` to ingestion-backend Dockerfile (was missing PostgreSQL driver)
6. **Docker Compose env** — frontend env vars changed from `VITE_API_URL=http://localhost:8007` to `VITE_API_URL=` (empty = relative) and `/scraper-api`, `/rag-api`

---

## Tech stack summary

| Layer | Choices |
|-------|---------|
| Languages | Python 3 (uv workspaces), TypeScript/React (ingestion UI) |
| APIs | FastAPI |
| Workers | Redis + RQ (scraper, rag eval); custom Redis queues (ingestion) |
| DB | Postgres 16 + SQLAlchemy + Alembic |
| Vectors | Qdrant v1.18 named dense + sparse |
| Models | LiteLLM proxy (OpenAI-compatible) at `host.docker.internal:4000` |
| Scraping | Playwright (Chrome in Docker) |
| Packaging | uv lockfiles, Docker Compose |
| Proxy | nginx:alpine |
| Reverse tunnel | ngrok (free domain, TLS termination) |
| Embeddings available | `all-MiniLM-L6-v2`, `nvidia-embed-passage`, `nvidia-embed-query`, `Qdrant/bm25` (sparse) |

---

## Documentation map

| Doc | Location |
|-----|----------|
| This overview | `PROJECT_OVERVIEW.md` |
| Bugs / security / reuse | `CODE_ANALYSIS.md` |
| Ingestion README | `ingestion-workspace/README.md` |
| RAG README | `rag-app-workspace/README.md` |
| Scraper deep dive | `web-scrapper-workspace/docs/PROJECT_EXPLAINED.md` |
| RAG plan | `rag-app-workspace/docs/plans/rag-platform-plan.md` |

---

## What is intentionally *not* at the root (yet)

- No root Makefile, Helm, or Terraform
- Shared installable package started: `shared-libs/platform-common` (vector + auth); embeddings/session helpers still per-workspace
- No root CI; only scraper has a GitHub workflow (ruff + docker build; pytest commented out)

---

## Change log

| Date | Notes |
|------|-------|
| 2026-07-17 | Initial project overview from source review |
| 2026-07-21 | **Complete operational overhaul**: |
| | - Custom Postgres init image (fix WSL bind-mount bug) |
| | - nginx reverse proxy for same-origin API access |
| | - Relative frontend API paths (fix ngrok CORS issues) |
| | - ngrok tunnel to Docker gateway IP |
| | - Vite allowedHosts for ngrok domain |
| | - Added `psycopg[binary]` to ingestion Dockerfile |
| | - Created `rag-shared` external network |
| | - All 12 containers running, migrations passing, ~93 vectors in Qdrant |
| | - E2E pipeline verified (crawl→scrape→embed→retrieve ✅, generate blocked by missing chat model) |
