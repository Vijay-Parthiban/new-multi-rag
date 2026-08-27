# RAG Full Pipeline — Project Overview

**Last reviewed:** 2026-07-17

This repository is a **loose monorepo** of three independently packaged products that together form an end-to-end RAG (Retrieval-Augmented Generation) platform: ingest documents and web content → embed into Qdrant → retrieve / rerank / generate → evaluate.

There is **no root shared Python package historically**. As of 2026-07-17, shared Qdrant/auth primitives live in `shared-libs/platform-common/` and are re-exported from each workspace. Remaining integration is still Docker, HTTP APIs, environment contracts, and the shared Qdrant payload schema.

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
| Backend API | `ingestion-backend/apps/api/` | FastAPI: uploads, directories, files, pipelines |
| Worker | `ingestion-backend/apps/worker/` | Redis queues + cron sync scheduler |
| File manager | `ingestion-backend/src/file_manager/` | Chunked upload, hashing, duplicate detection, storage |
| Ingestion service | `ingestion-backend/src/ingestion_service/` | Pipeline/sync runners, indexer, Qdrant write |
| Shared | `ingestion-backend/src/shared/` | Settings, DB models/session, Redis, auth |
| Frontend | `ingestion-frontend/` | React pages for upload, browse, pipelines, tracking, chat, eval |
| Compose | `docker-compose.yaml` | **Unified stack**: Postgres, Redis, Qdrant, scraper image, RAG build, ingestion |

**Key env:** `DATABASE_URL`, `REDIS_URL`, `STORAGE_PATH`, `QDRANT_*`, `LITELLM_BASE_URL`, `OPENAI_API_KEY`, `SCRAPER_API_URL`, `API_KEY`, `VITE_API_URL`, `VITE_SCRAPER_URL`, `VITE_RAG_API_URL`.

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

### Shared-Libs (`platform-common`) Usage

Because the project relies on a unified Qdrant vector database and unified API specifications, the foundational primitives are stored in `shared-libs/platform-common/` and are consumed globally:

- **`web-scrapper-workspace`**: Uses the shared auth logic (`make_verify_api_key`), dense and sparse embedding clients, Qdrant store interfaces, hit mappers, and depends heavily on `ssrf.py` to securely validate seed URLs before executing headless browser tasks.
- **`rag-app-workspace`**: Reuses the Qdrant read schemas (including `DENSE_VECTOR_NAME`, `SPARSE_VECTOR_NAME`), the exact hit mappers to translate Qdrant chunks payload to generic RAG structures, embedding generation clients, and configures API routes via the shared `auth.py`.
- **`ingestion-workspace`**: Inserts files into Qdrant directly using the shared `QdrantVectorStore`, creates both sparse/dense multimodal vectors utilizing the shared embedding clients, and secures pipelines with the shared auth structures.

While the workspaces operate independently as microservices, they are inherently tied together by this strict architecture living at the root `shared-libs`.

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

## Evaluation Metrics (Golden & Live Chat)

The `eval-core` library handles the computation of metrics across the platform, applicable both to live conversational chat traces and offline golden datasets. The metrics are generated using a mix of standard Information Retrieval (IR) algorithms and the `ragas` framework powered by LLM (LiteLLM proxy) judge capabilities.

### 1. Chat Metrics (Live conversational traces)
For live chat, metrics are typically computed asynchronously (via RQ workers) after a response is sent to avoid latency impacts.
- **RAGAS Generation Metrics:**
  - `faithfulness`: Measured using `Ragas Faithfulness`. It ensures that the generated output does not hallucinate information outside of the retrieved contexts.
  - `answer_relevancy`: Assesses how pertinent the generated answer is to the user's question, penalizing redundant or incomplete answers.
- **Retrieval Fallback:** In live chat, since we lack an explicit "expected source" context, we rely on semantic relevance or rely primarily on the RAGAS context metrics. 

### 2. Golden Evaluation Metrics (Offline offline dataset evaluation)
For ground-truth evaluation, human loop provided datasets (query, contexts, ground_truth, sources) are passed through the RAG pipeline.
- **Classic IR Metrics:**
  - `mrr`, `mrr_before`, `mrr_after`: Mean Reciprocal Rank indicating the rank at which the first relevant document was retrieved.
  - `hit_at_k`: Binary measure of whether a relevant document appeared in top-K results.
  - `precision_at_k`: The proportion of top-K retrieved chunks that match expected sources.
  - `recall_at_k`: The proportion of all manually expected sources that were successfully retrieved in the top-K chunks.
  - `ndcg`: Normalized Discounted Cumulative Gain, useful for scoring ranked outputs.
  - `kendall_tau`: Evaluates the correlation of ranks before and after the reranking phase.
- **RAGAS Retrieval Metrics:**
  - `context_precision` and `context_recall`.
- **RAGAS Correctness Metrics:**
  - `answer_correctness`: Used when a ground truth answer is available, checking factual overlap between generated answer and ground truth.

### Handling Multi-Hop Reasoning (Multiple Expected Sources)
When evaluating queries that require multi-hop reasoning, the expected ground truth typically spans multiple distinct documents or, specifically, **multiple pages of the same or different documents**. 
- The `ExpectedSource` parser (in `eval-core/source_match.py`) allows defining expected sources as objects mapping to a specific `name` and specific `page` number.
- **Source Matching:** A chunk is considered "relevant" if it satisfies both the target file locator (URL, filename) and the exact `page_index`/`page_num`.
- **Retrieval Evaluation:** 
  - For `recall_at_k`, the eval engine checks each expected source separately. If a query requires two pages (A and B), recall will equal `0.5` if only one is retrieved, and `1.0` if both are found in the top-K results.
  - For `mrr`, it considers the rank of whichever required source appears highest in the retrieved results.
  - During reranking evaluation (`mrr_after`), it guarantees that the reranker surfaces chunks from both pages required for the LLM to successfully synthesize a multi-hop answer.

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
