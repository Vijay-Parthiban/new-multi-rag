# RAG Full Pipeline — Project Overview

**Last reviewed:** 2026-07-31

This repository is a **loose monorepo** of three independently packaged products that together form an end-to-end RAG (Retrieval-Augmented Generation) platform: ingest documents and web content → embed into Qdrant → retrieve / rerank / generate → evaluate.

There is **no root shared Python package historically**. As of 2026-07-31, shared Qdrant/auth primitives live in `shared-libs/platform-common/` and are re-exported from each workspace. Remaining integration is still Docker, HTTP APIs, environment contracts, and the shared Qdrant payload schema.

**Key Update:** Sources page implementation completed in ingestion-workspace (see below).

---

## Top-level layout

```text
rag-full-pipeline/
├── PROJECT_OVERVIEW.md          ← this file
├── CODE_ANALYSIS.md             ← bugs, security, reuse plan
├── shared-libs/
│   └── platform-common/         ← shared auth + Qdrant helpers
├── ingestion-workspace/         ← upload UI + file indexing + orchestration
├── web-scrapper-workspace/      ← crawl → scrape → embed → Qdrant write
└── rag-app-workspace/           ← retrieve → rerank → generate → eval
```

| Workspace | Role | Default ports |
|-----------|------|---------------|
| **ingestion-workspace** | Document upload, pipeline config, file→Qdrant indexing, end-to-end UI | Frontend `5173`, API `8007` |
| **web-scrapper-workspace** | Web crawl/scrape, embeddings, shared infra (Postgres/Redis/Qdrant) | API `8000` |
| **rag-app-workspace** | RAG API + eval worker (reads Qdrant) | API `8001` |

---

## System architecture

```text
┌──────────────────────────────────────────────────────────────────────────┐
│  ingestion-frontend (React/Vite)                                         │
│    Upload · Browse · Pipelines · Tracking · Chat · Evaluations           │
└────────────┬──────────────────┬───────────────────────┬──────────────────┘
             │                  │                       │
             ▼                  ▼                       ▼
      Ingestion API      Scraper API              RAG API
         :8007              :8000                   :8001
             │                  │                       │
             │                  │                       │
             ▼                  ▼                       ▼
      Postgres DB          Postgres DB            Postgres DB
       `ingestion`          `crawler`                `rag`
             │                  │                       │
             │         Redis RQ (crawl/scrape)     Redis RQ (eval)
             │                  │                       │
             └──────────┬───────┴───────────────────────┘
                        ▼
                   Qdrant :6333
              collection: scrape_embeddings
              named vectors: dense + sparse
                        ▲
                        │
              LiteLLM (host :4000)
           embeddings · chat · rerank · RAGAS
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
| Backend API | `ingestion-backend/apps/api/` | FastAPI: uploads, directories, files, pipelines, **sources** |
| Worker | `ingestion-backend/apps/worker/` | Redis queues + cron sync scheduler |
| File manager | `ingestion-backend/src/file_manager/` | Chunked upload, hashing, duplicate detection, storage |
| Ingestion service | `ingestion-backend/src/ingestion_service/` | Pipeline/sync runners, indexer, Qdrant write |
| Shared | `ingestion-backend/src/shared/` | Settings, DB models/session, Redis, auth |
| Frontend | `ingestion-frontend/` | React pages for upload, browse, pipelines, tracking, chat, eval, **sources** |
| Compose | `docker-compose.yaml` | **Unified stack**: Postgres, Redis, Qdrant, scraper image, RAG build, ingestion |

**Key env:** `DATABASE_URL`, `REDIS_URL`, `STORAGE_PATH`, `QDRANT_*`, `LITELLM_BASE_URL`, `OPENAI_API_KEY`, `SCRAPER_API_URL`, `API_KEY`, `VITE_API_URL`, `VITE_SCRAPER_URL`, `VITE_RAG_API_URL`.

**Queues:** `file_manager:jobs`, `ingestion:pipeline:jobs`, `ingestion:sync:jobs`.

#### Sources Page (New Feature)
As of 2026-07-31, the ingestion-workspace includes a **Sources** page for managing external data sources via Airbyte connectors:
- Create, read, update, delete sources with configurable connectors (Google Drive, GCS, S3, Azure Blob, SharePoint, etc.)
- Each source gets a dedicated MinIO bucket for storage
- Live (continuous) or scheduled monitoring modes
- Pipeline linking: sources can be linked to one or more RAG pipelines for automatic re-indexing
- File-level CRUD operations trigger incremental pipeline re-indexing of only changed files
- Backend API fixes applied to resolve MissingGreenlet errors and S3 bucket handling

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

**Key env:** `DATABASE_URL`, `REDIS_URL`, `QDRANT_*`, `LITELLM_*`, model names, `API_KEY`, RAGAS/eval flags.

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
| Frontend → Scraper | Tracking: `/crawls`, `/scrapes` |
| Frontend → RAG | Chat/eval: `/chat`, sessions, metrics, evaluate |
| RAG → Qdrant | Direct client (no scraper HTTP for retrieval) |

---

## Runtime topologies

### A. Unified (recommended for full pipeline)

From `ingestion-workspace/`:

```bash
docker compose up --build
```

Owns Postgres (DBs `ingestion`, `crawler`, `rag`), Redis, Qdrant; pulls scraper image; builds RAG + ingestion services.

### B. Split stack

1. Start `web-scrapper-workspace` (infra + `rag-shared` network).
2. Create Postgres DB `rag`.
3. Start `rag-app-workspace` attached to external `rag-shared`.
4. Optionally run ingestion against those services.

**External dependency:** LiteLLM on the host at `:4000` (`host.docker.internal`).

---

## Tech stack summary

| Layer | Choices |
|-------|---------|
| Languages | Python 3 (uv workspaces), TypeScript/React (ingestion UI) |
| APIs | FastAPI |
| Workers | Redis + RQ (scraper, rag eval); custom Redis queues (ingestion) |
| DB | Postgres 16 + SQLAlchemy + Alembic |
| Vectors | Qdrant v1.18 named dense + sparse |
| Models | LiteLLM proxy (OpenAI-compatible) |
| Scraping | Playwright |
| Packaging | uv lockfiles, Docker Compose |

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
