# End-to-End Architecture & Operational Manual — new-multi-rag

**Last updated:** 2026-10-09

## 1. System Architecture Overview
The **`new-multi-rag`** platform is an enterprise-grade, distributed Retrieval-Augmented Generation (RAG) system composed of two decoupled and complementary subsystems:

1. **`rag-ingestion-manager`** (Frontend: Port `5173`, Backend: published on host port `8007` / container port `8000`):
   - Ingestion perimeter. Two bucket source types are creatable: **Apache NiFi Connector Source** and **Manual Upload Source** (`backend/apps/api/routes/sources.py:277-382`). The connector catalogue is NiFi-only and holds exactly three ids — `google_drive`, `s3`, `azure_blob` (`sources.py:35-41`); connector pulls are executed by the NiFi-based engine (`src/ingestion_service/core/nifi_sync.py`). Legacy connector rows for other ids still resolve and can be edited, but no new one can be attached.
   - Each connector chooses **live** polling (fixed 3-second loop) or **scheduled** polling with an interval in **seconds or minutes** (`sync_interval_seconds`, added 2026-09-20, takes priority over `sync_interval_minutes`).
   - Document staging, change detection over the object ETag and size (`src/ingestion_service/core/universal_fanout.py`), multi-format parsing and text chunking with one of eight strategies.
   - Every source owns a MinIO bucket named `<MINIO_BUCKET_PREFIX>-<source name>-<source id[:8]>` (default prefix `source`, `src/shared/config/settings.py:44`, `backend/apps/api/routes/sources.py:255-259`); legacy local-filesystem sources live under `storage/local_sources/<folder>`. Deleting a source empties and removes its bucket.
   - **Universal 4-Destination Fanout Engine** (`src/ingestion_service/core/universal_fanout.py`) syncing documents into 4 destination types, written **in parallel per file** via `asyncio.gather(..., return_exceptions=True)` with per-destination error isolation: **Dense Vector Store (Qdrant)**, **Sparse Vector Store (OpenSearch)**, **Relational Chunk Store (Postgres)** and **Cache Store (Redis VL)** — the four `name` values `build_destination_types()` returns (`backend/apps/api/routes/knowledge_destination_schemas.py`). Each Knowledge Product writes to its own store names (`kp_<slug>_<id8>`).
   - **Product lifecycle purge**: deleting a Knowledge Product triggers `purge_knowledge_product()`; a changed or deleted file is purged from every destination that holds it, keyed on `(source_id, file_key)` (`universal_fanout.py`, `backend/apps/api/routes/knowledge_products.py`).
   - **Ingestion modality and page images**: an Ingestion Profile carries `modality_mode`, `chunk_strategy`, `chunk_config`, `text_embedding_model` and `image_embedding_model` (`src/shared/db/models.py`). `text` (default) reads selectable text and tables, then chunks them with the profile's strategy. `chunk_config` holds the settings of that strategy, keyed by parameter name. The catalogue of eight strategies — Recursive, Fixed-Size, Structure-Aware, Semantic, Parent-Child, Contextual, Page-Level and Sentence-Window — is served by `GET /api/ingestion-profiles/chunk-strategies`, so the form holds no strategy knowledge. `text_images` renders each document page to a PNG at 150 dpi, writes it to the source bucket under `_pages/`, and embeds it with `image_embedding_model` through `EmbeddingClient.embed_image_png`. It stores one record per page (`modality="image"`, `record_type="page"`) with the page text as `content` and `text`, and runs no chunking; `type` stays `"text"` so the retrieval consumers keep their shape. A page that renders no image — every text format, and a PDF page that cannot be rasterised — takes the ordinary text path with `text_embedding_model` and `modality="text"`. The sync summary key is `pages_without_image`. An empty `image_embedding_model` on a `text_images` profile is rejected with `422 IMAGE_EMBEDDING_MODEL_REQUIRED`, and an unknown `chunk_config` key with `422 CHUNK_CONFIG_INVALID`. The caption path is removed. **OCR is not implemented.**
   - **Derived vector dimension**: the profile no longer configures `vector_size`. The fanout embeds each chunk once per tick and takes the dimension from the embedding model output. Every vector destination reuses that one vector. The fanout rejects a batch whose vectors have mixed lengths, because a failed proxy call can fall back to a local 384-dimension model. It refuses to recreate an existing Qdrant collection whose dimension disagrees, because recreation deletes every point.
   - **One sync per Knowledge Product**: `sync_knowledge_product()` takes a cross-process Redis lock `knowledge:sync:lock:<product_id>` with a 900-second TTL. The lock exists because the API host polls the product while the pathway worker kicks the same product after a source change. Both could fan out the same file, and three stores then held duplicate documents. The lock releases with a compare-and-delete script, so it cannot delete another holder's lock.
   - **Multi-format parsing** via `page_yielder.py`, which yields one page at a time: PDF (PyMuPDF), DOCX, CSV, JSON, Markdown/plain text, with a UTF-8 fallback for unknown types (`src/ingestion_service/core/page_yielder.py:36-93`). `iter_file_pages` takes `render_pages` (default `True`) and `render_dpi` (default 150); the text path passes `render_pages=False` and reads no page raster. `FilePage.__post_init__` strips every NUL byte (`0x00`) from a page's text, because psycopg2 refuses a string that holds one and the relational destination then fails the whole insert; the strip happens before any chunker or writer sees the text (`tests/test_page_yielder.py::test_nul_byte_removed`). Chunking uses one of eight strategies and reads the selected strategy's settings from `chunk_config`, with the window defaulting to `chunk_size=1000` / `chunk_overlap=120` (`src/ingestion_service/utils/text_splitter.py:351-358`, `src/shared/db/models.py:117-118`).
   - **Typed destination configuration**: `GET /api/knowledge-products/destinations/options` returns Docker-aware defaults, per-field schemas and `namespace_fields` (`routes/knowledge_destination_schemas.py`), and `GET /api/knowledge-products/config/litellm-models` lists models from the LiteLLM proxy with an environment fallback (`routes/knowledge_products.py`).
   - **Interactive Multi-Destination Visualizers** via `GET /api/knowledge-products/{product_id}/inspect/{destination_type}` (four destination branches).
   - **Uploads happen on the Knowledge Fabric page.** The standalone Upload page (`/upload`) was removed on 2026-09-20, and the page that carries the upload action was renamed from *Sources* to **Knowledge Fabric** on 2026-10-01. Create a Manual Upload Source, or use the **Upload Files** action on a manual source, to write files into that source's MinIO bucket. The chunked-upload API (`/api/uploads/*`) remains but has no UI caller.

2. **`rag-retrieval-chat-manager`** (Frontend: Port `5174`, Backend: Port `8001`):
   - Multi-stage retrieval and conversational intelligence gateway (`apps/rag-api/src/rag_api/main.py`, `create_app()`).
   - Hybrid dense/sparse retrieval: one Qdrant query with dense `prefetch` plus sparse `Qdrant/bm25` prefetch (IDF modifier) fused with Reciprocal Rank Fusion (`libs/vector-core/src/vector_core/search.py:17-53`, `shared-libs/platform-common/src/platform_common/vector/qdrant_store.py:245-274`). Defaults: `default_retrieval_mode=hybrid`, `retrieve_limit=20` (`libs/shared/src/rag_shared/config.py:64-65`).
   - Reranking through the LiteLLM `POST /v1/rerank` endpoint (`libs/reranker-core/src/reranker_core/litellm_reranker.py`), default model `nvidia-rerank`, `rerank_top_k=5` (`config.py:67-69`); `NoopReranker` when disabled. An assistant pipeline can save its own `retrieve_limit`, `rerank_enabled` and `rerank_top_k`, which a turn takes when the request names none.
   - Context-grounded generation over LiteLLM with streaming SSE, vision multimodal inputs and dynamic prompt templating. Defaults: `chat_model=llama-3.3-70b-versatile`, `vision_model=groq-vision`, `fusion_model=llama-3.3-70b-versatile` (`config.py:36-38`).
   - Safety guardrails delegate to the standalone `guardrails-service` (Guardrails AI) over HTTP. The service holds the validator catalog: three validators. Two are real PyPI packages, `guardrails-ai-ban-list` and `guardrails-ai-detect-pii`. One is a local LLM judge registered as `local/toxic_language` that calls the LiteLLM proxy (`guardrails-service/config.py`, `guardrails-service/server.py`). It exposes `GET /catalog`, `POST /validate`, `POST /validate-config` and `GET /health-check` (`guardrails-service/server.py:45-69`). The retrieval API proxies the catalog for the Guard Config page and validates a saved config through `POST /validate-config` before it stores it (`rag_api/routes/guardrails.py:231`). The shared HTTP client defaults to `http://localhost:18000` (`libs/shared/src/rag_shared/guardrails_client.py:65`), and the ingestion compose file publishes the service on host port `18000` (`rag-ingestion-manager/docker-compose.yaml:306-317`). Chat requests optionally bind a stored guardrails config.
   - Continuous observability through the OpenTelemetry collector in `otel/` (Phoenix and Langfuse exporters, with Arize AX and Grafana Cloud kept as commented examples), and Ragas evaluation both online (per chat message) and offline (golden datasets), with the RQ `eval` queue on Redis (`config.py:16-18`).

---

## 2. End-to-End Data & Execution Lifecycle

```
========================================================================================================================
                                             PHASE 1: DATA INGESTION & 4-DESTINATION FANOUT
========================================================================================================================
[ External Sources / Connectors ]  --->  [ MinIO Object Store ]  --->  [ Ingestion Backend :8007 ]
(Google Drive, S3, Azure, SFTP,          (one bucket per source:      - Extract & Parse (PDF/DOCX/CSV/JSON/MD/TXT)
 Confluence, Manual upload, NiFi engine)  source-<name>-<id8>)        - ETag + Size Change Detection
                                                                      - Chunking per Profile (1000/120 default) 
                                                                      - Dense Embeddings via LiteLLM
                                                                        (nvidia-embed-textonly default)
                                                                                    |
                                                                                    v
                                                                    [ Universal Fanout Engine ]
                                                                      (universal_fanout.py)
                                                       asyncio.gather per file, per-destination isolation
                                                                                    |
            +-----------------------+-----------------------+-----------------------+-----------------------+
            |                       |                       |                       |
            v                       v                       v                       v
    +-----------------------+   +-----------------------+   +-----------------------+   +-----------------------+
    | 1. Dense Vector Store |   | 2. Sparse Vector Store|   | 3. Relational Chunk   |   | 4. Cache Store        |
    |     (Qdrant)          |   |     (OpenSearch)      |   |     Store (Postgres)  |   |     (Redis VL)        |
    | dense HNSW (cosine)   |   | BM25 inverted index   |   | pgvector chunk table  |   | chunk cache, optional |
    |                       |   |                       |   |                       |   | RAPTOR summaries      |
    +-----------------------+   +-----------------------+   +-----------------------+   +-----------------------+

========================================================================================================================
                                           PHASE 2: RAG RETRIEVAL, SYNTHESIS & EVALUATION
========================================================================================================================
[ User / Chat Client ] -> rag-retrieval-chat-manager :8001
        |
        v
[ Guardrails Check ] (guardrails-service -> POST /validate)
        |  [Blocked -> returned as blocked result; trace rows stored in Postgres]
        v  [Passed -> Proceed]
[ Hybrid Retrieval Engine ] (RAGPipeline.retrieve -> Retriever -> vector_core.search)
   |-- One Qdrant query on collection `scrape_embeddings`
   |-- Dense named vector (LiteLLM embedding via shared EmbeddingClient, input_type=query,
   |    platform_common/embeddings/dense.py:40-50)
   |-- Sparse named vector (fastembed `Qdrant/bm25`, IDF)
   |-- Reciprocal Rank Fusion of both prefetches
        |
        v
[ LiteLLM Reranker ] (POST /v1/rerank, default `nvidia-rerank`, top-N = 5)
        |
        v
[ Generation Engine (LiteLLM) ] (system prompt + cited context + query -> chat / vision model)
        |
        v
[ Streaming Token Delivery to User ] + [ OpenTelemetry Trace Export ] + [ Async Ragas Metrics (RQ `eval` queue) ]
```

---

## 3. Storage Layer Matrix & Port Allocations

| Service / Sink | Default Port | Internal Role & Data Payload |
|---|---|---|
| **RAG Ingestion Backend** | `8007` (host) → `8000` (container) | FastAPI ingestion gateway, connector sync, fanout engine, sink inspection APIs (`docker-compose.yaml:23`, `backend/scripts/run-api.sh:3`) |
| **RAG Ingestion Frontend** | `5173` | Vite/React dashboard, file browser, sources manager, 4-destination visualizer modals (`frontend/vite.config.ts:8`; dev proxy `/api` → `http://127.0.0.1:8007`, `:11`) |
| **RAG Retrieval Backend** | `8001` | FastAPI chat, hybrid retrieval, reranking, generation, guardrails, eval APIs (`libs/shared/src/rag_shared/config.py:50`, `backend/docker-compose.yaml:19`) |
| **RAG Retrieval Frontend** | `5174` | Vite/React chat interface, pipeline manager, prompt studio, trace viewer (`frontend/vite.config.ts:8`) |
| **Guardrails Service** | `18000` (host) → `8000` (container) | Guardrails AI service exposing `GET /catalog` for the 3 validators in its catalog, plus `POST /validate` and `POST /validate-config` (`guardrails-service/server.py`, `docker-compose.yaml`) |
| **Web-Scrapper API** | `8000` | Crawl/scrape service from `web-scrapper-workspace`; shares Postgres, Redis and Qdrant (`docker-compose.yaml:142`) |
| **LiteLLM proxy** | `4000` | External (host-run) OpenAI-compatible proxy for embeddings, rerank, chat and vision (`settings.py:21`, `rag_shared/config.py:24`) |
| **MinIO Object Storage** | `9000` / `9001` | Raw document binaries, one bucket per source named `source-<name>-<id[:8]>` (`docker-compose.yaml:76-77`, `routes/sources.py:259`) & console |
| **Qdrant Vector DB** | `6333` | Named dense + sparse vectors. **One instance serves both projects:** the compose service `rag-ingestion-manager-qdrant-1` publishes host `6333` and holds everything. The scraper writes `scrape_embeddings` to it, and the ingestion fanout writes the `kp_<slug>_<id8>` collections to the same server. Both backends reach it by the Docker DNS name `qdrant:6333`, and both set `QDRANT_URL` and `QDRANT_KP_URL` to it. The fanout takes the dimension from the embedding model output. It refuses to recreate an existing collection whose dimension disagrees, because recreation deletes every point |
| **OpenSearch** | `9200` | Full-text BM25 lexical inverted index. Each Knowledge Product writes its own index `kp_<slug>_<id8>` (`knowledge_destination_schemas.py`); performance analyzer on `9600`, dashboards on `5601` (`docker-compose.yaml:330-331,342`) |
| **Neo4j Graph DB** | `7474` / `7687` | The compose service, its `neo4j_data` volume and the `extras` profile entry stay declared, but the `graph_neo4j` destination was removed on 2026-09-20, so no destination reads or writes Neo4j. It is dead weight behind the `extras` profile. `scripts/purge_neo4j_legacy.py` deletes the previously written `Chunk`/`Document`/`Entity` nodes. |
| **PostgreSQL DB** | `5432` | Three databases: `ingestion` (ingestion API metadata, user/password `ingestion`), `rag` (retrieval: chat, evaluation and guardrails tables in `libs/database/src/rag_db/models/`), and `crawler` (web-scrapper job history). All three share the role `crawler:crawler`, which must exist for `rag` and `crawler`. Each Knowledge Product gets its own pgvector schema `kp_<slug>_<id8>` with a `chunks` table (`universal_fanout.py`). The writer creates an HNSW index with `USING hnsw (embedding vector_cosine_ops)`. pgvector caps an HNSW index at 2000 dimensions. Above that limit the writer skips the index with a warning, and a search falls back to an exact scan. The embedding model in use returns 2048 dimensions, so this is the normal path here. There is one database: PostgreSQL. The SQLite fallback is removed, and an unreachable database stops the service |
| **Redis / RedisVL** | `6379` | Ingestion RQ queues `file_manager:jobs`, `ingestion:pipeline:jobs`, `ingestion:sync:jobs` (`settings.py:12-14`); RedisVL sink writes `<prefix>:<source_id>:<file_key>:<page_index>:<chunk_index>` keys with a 24 h TTL, where the prefix is the product's `kp:<slug>:<id8>` (`knowledge_destination_schemas.py`, `universal_fanout.py`). It also holds the cross-process sync lock `knowledge:sync:lock:<product_id>` with a 900-second TTL. The retrieval RQ `eval` queue (`rag_shared/config.py:18`) |
| **OpenTelemetry Collector** | `4317` (gRPC) / `4318` (HTTP) | Receives OTLP traces/metrics/logs and fans out traces to Phoenix and Langfuse (`docker-compose.yaml:198-199`, `otel/otel-collector-config.yaml`) |

---

## 4. Operational Runbook & Verification

> **For a complete start-to-finish run guide for both projects and every dependency, see
> [`two_project_run.md`](./two_project_run.md).** It is the authoritative run document: the full port
> and service matrix, the three containers that live outside this repository, the environment block
> for each backend, the start order, the first-run walkthrough, and a troubleshooting table. This
> section keeps the shorter reference and the verification assets.

**Full stack (Docker Compose).** The ingestion compose file is the only one that brings up the shared infrastructure (Postgres, Redis, Qdrant, MinIO, OpenSearch, web-scrapper, guardrails service, OTel collector). A Neo4j service is still declared there, but no destination uses it. Build contexts are the monorepo root, so it must be run from its own directory:

```bash
cd rag-ingestion-manager
docker compose up --build
```

**Ingestion Manager Backend** (module `apps.api.main:app`; the container runs the same app on `8000`, published as `8007` by compose):

```bash
cd rag-ingestion-manager/backend
uv run uvicorn apps.api.main:app --host 0.0.0.0 --port 8007
```

**Ingestion Manager Frontend** (the Vite config already fixes port `5173`):

```bash
cd rag-ingestion-manager/frontend
npm run dev
```

**Retrieval Chat Manager — prerequisites.** `backend/.env` holds Docker service hostnames (`postgres`, `redis`, `qdrant`), which do not resolve from the host. Pass host overrides as process environment; a real environment variable wins over the `.env` file in pydantic-settings. One Qdrant on `6333` serves both projects. It holds the scraper's `scrape_embeddings` and every `kp_*` collection. `QDRANT_URL` and `QDRANT_KP_URL` name the same server.

```bash
cd rag-retrieval-chat-manager/backend
uv sync --all-packages     # `uv sync` alone installs only the root project, not the libs/apps

# Once, in the running Postgres: a `rag` database and a `crawler` login role.
# The retrieval URL is postgresql+psycopg://crawler:crawler@<host>:5432/rag
```

**Retrieval Chat Manager Backend** (module `rag_api.main:app`, port `8001`):

```bash
cd rag-retrieval-chat-manager/backend
DATABASE_URL="postgresql+psycopg://crawler:crawler@localhost:5432/rag" \
REDIS_URL="redis://localhost:6379/0" \
QDRANT_URL="http://localhost:6333" \
LITELLM_BASE_URL="http://localhost:4000" \
OTEL_TRACING_ENABLED=true \
OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318" \
  uv run uvicorn rag_api.main:app --host 0.0.0.0 --port 8001
```

`scripts/run-api.sh` runs the same module but reads `backend/.env`, so it only works inside the compose network. The usual host run needs neither prefix nor export: `Settings` reads `backend/.env` and then `backend/.env.local`, and the later file wins, so the gitignored `.env.local` already carries `localhost` for every service, `OTEL_TRACING_ENABLED=true` and `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`.

**Keep tracing on for a real run.** A `false` in `.env.local` overrides the `true` in `.env`, and then the app never starts a tracer: no span leaves it, so nothing reaches Langfuse or Phoenix, for a `test` turn and a `prod` turn alike. Nothing logs an error, because the failure is an absent exporter rather than a failed one. The host target has to be `http://localhost:4318`; the `http://otel:4318` in `.env` is the compose service name and does not resolve from the host. Confirm spans are arriving with `docker logs --since 5m otel | grep -c '"otelcol.component.id": "debug"'`, one line per accepted batch.

**Retrieval Chat Manager Frontend** (Vite config fixes port `5174`). It sets no dev proxy, so the browser calls `8001` and `8007` directly and `api.ts` supplies those defaults; no `.env` is needed. On Windows `npx vite` fails to spawn, so call the entry script through `node`:

```bash
cd rag-retrieval-chat-manager/frontend
node node_modules/vite/bin/vite.js --force --host 0.0.0.0 --port 5174
```

**Retrieval Chat Manager worker / migrations** (same env overrides; migrations must run before the API):

```bash
cd rag-retrieval-chat-manager/backend
DATABASE_URL="postgresql+psycopg://crawler:crawler@localhost:5432/rag" uv run rag-db-migrate
uv run rq worker eval --url redis://localhost:6379/0
```

**Web-Scrapper API** (port `8000`; the ingestion scraper path and `scrape_embeddings` depend on it). It runs on the host now, from its own project, so its code hot-reloads. It needs a `crawler` database, whose tables `crawler-db-migrate` creates:

```bash
sh scripts/dev.sh scraper-api     # runs crawler-db-migrate first, then uvicorn :8000 --reload
sh scripts/dev.sh scraper-worker  # separate terminal
```

The container form is still available behind a profile, for a machine without a host checkout:

```bash
cd rag-ingestion-manager
docker compose --profile scraper up -d --no-recreate scraper-migrate scraper-api scraper-worker
```

`--no-recreate` stops compose from rebuilding the shared Postgres, Redis and Qdrant containers that the ingestion stack is already using.

**Guardrails service** (published on `18000` by the ingestion compose file):

```bash
cd rag-ingestion-manager
docker compose up -d guardrails-service
```

Verification assets that exist in the tree:
- Ingestion E2E fanout scripts: `rag-ingestion-manager/backend/scripts/e2e_knowledge_fanout.py` and `rag-ingestion-manager/backend/scripts/e2e_knowledge_pause.py`
- Legacy Neo4j purge script: `rag-ingestion-manager/backend/scripts/purge_neo4j_legacy.py`
- Ingestion unit tests: `rag-ingestion-manager/backend/tests/test_page_yielder.py` (holds `test_nul_byte_removed` and the `render_pages` / `render_dpi` cases), `test_embedding_image_failure.py`, `test_fanout_payload.py`, `test_knowledge_destination_schemas.py`, `test_knowledge_product_files.py`, `test_connector_config_validation.py`, `test_ingestion_profile_chunking.py`, `test_ingestion_modality_resolvers.py` and `test_source_webscrape.py`; the suite is green on 2026-10-02
- Shared library unit tests: `shared-libs/platform-common/tests/test_ssrf.py` and `tests/test_embed_batches.py`, which pins the 256-input embedding batch cap
- Retrieval unit tests: `rag-retrieval-chat-manager/backend/tests/unit/` (16 modules, run with `uv run pytest tests/unit -v`); integration test `tests/integration/test_qdrant_retrieve.py` (requires a reachable Qdrant)

---

## 5. Shared Library & Cross-Service Contracts

`shared-libs/platform-common/` (`platform_common`) is the shared integration layer used by ingestion, retrieval and the web-scrapper:

| Module | Role |
|---|---|
| `platform_common/auth.py` | API key verification via `X-API-Key` header **or** `api_key` query parameter (`:12`, `:32`); no-op when the configured key is empty, `/health`, `/docs`, `/openapi.json` and `/redoc` bypass auth (`:11`). Both backends build their dependency with `make_verify_api_key` (`src/shared/auth.py:8`, `rag_shared/auth.py:8`) |
| `platform_common/vector/qdrant_store.py` | Qdrant collection management. The retrieval wrapper accepts a per-call `url`, which is how a knowledge product collection is reached from the reader that also serves the scraper's `scrape_embeddings`. `ensure_collection()` accepts optional `hnsw_m` and `hnsw_ef_construct` tuning. It raises when the stored vector size disagrees with the derived dimension, because recreation deletes every point (`:82-90`) |
| `platform_common/vector/hit_mapper.py` | Retrieval payload contract: `source_type`, `source_id`, `source_locator`, `content`, `chunk_index`, `title`, `file_name`, `page_index`, `file_key` (`:20-48`). `file_key` is what identifies one chunk across Qdrant, OpenSearch and pgvector, because the fanout writes the same value to each; the hybrid reader fuses on it |
| `platform_common/vector/filters.py` | `source_type` / `source_id` Qdrant filter construction |
| `platform_common/embeddings/dense.py`, `sparse.py` | LiteLLM dense embedding client and cached fastembed sparse client |
| `platform_common/types.py` | `SearchMode`, `SourceTypeFilter`, `FILE_INGEST_SOURCE_TYPE`, `WEB_SCRAPE_SOURCE_TYPE` |
| `platform_common/ssrf.py` | `validate_public_http_url` / `UnsafeURLError` for connector URLs |

`shared-contracts/` (`shared_contracts`, a Pydantic-only package consumed by the ingestion backend and by retrieval `libs/shared`) holds the cross-service models:

| Module | Role |
|---|---|
| `shared_contracts/knowledge.py` | `KnowledgeProductRead/Create/Update`, `KnowledgeProductSourceRead`, `KnowledgeDestinationConfigRead`, `DestinationConfigInput`, `MonitorMode`, `SinkType = vector_qdrant \| lexical_opensearch \| relational_pgvector \| cache_redisvl` |
| `shared_contracts/sources.py` | `SourceRecordBase`, `SourceRecordCreate`, `SourceRecordRead` |
| `shared_contracts/search.py` | `SearchHitContract`, `HybridRetrievalRequest` |
| `shared_contracts/pipelines.py` | `PipelineConfigContract`, `RAGTraceContract` |

Ingestion fanout payloads are built by `_build_fanout_payload()` (`universal_fanout.py`) with the `knowledge_product_id` key, so retrieval and visualizers stay aligned. The payload also carries `modality` (`text` or `image`) and `image_ref`; a `text_images` page record names the stored page PNG in `image_ref`, and `type` stays `"text"` so the retrieval consumers keep their shape.

**Retrieval Knowledge Store path.** The retrieval backend only *proxies* knowledge products over HTTP to the ingestion manager: `apps/rag-api/src/rag_api/routes/knowledge.py` mounts `APIRouter(prefix="/api/knowledge-products")` and every route forwards to the resolved setting `settings.ingestion_service_url` (default `http://localhost:8007`, `libs/shared/src/rag_shared/config.py:48`), returning `503` when the ingestion service is unreachable. The proxies are list/create/get/update/delete (update is `PATCH`) and `POST /{id}/test-connection`; the manual sync proxy is gone. There is no ingestion database access from the retrieval side. The retrieval frontend's Knowledge Store page calls the ingestion API directly, since its API client resolves `VITE_API_URL` (default `http://127.0.0.1:8007`, `frontend/src/api.ts:6`) through `apiFetch` (`frontend/src/api.ts:375-429`).

---

## 6. Recent Platform Updates (2026-09)

| Area | Change |
|---|---|
| **Sources page (2026-09-20)** | Upload page removed. Two bucket source types only: **Apache NiFi Connector Source** and **Manual Upload Source**. Connector catalogue narrowed to three NiFi-only ids (`google_drive`, `s3`, `azure_blob`); one source can hold many connectors. Each connector picks live polling or a scheduled interval in seconds or minutes. Source delete asks in an in-app confirmation dialog showing the bucket and object count, then empties and removes the MinIO bucket. See `vijay-docs/rag-ingestion-manager-docs/03_data_sources_page.md` |
| **Sources page pause (2026-09-20)** | The manual **Sync All Connectors** / **Sync Now** buttons are gone. Polling is automatic from the moment a connector is saved; the UI now exposes **Pause All Connectors** / **Pause** (and Resume) that flip `SourceConnector.enabled`. `register_source_poller` derives mode and interval from the enabled connectors instead of the source-level default, and stops the poller when every connector is paused. Connector buckets show no file actions; manual buckets keep Delete but lose "Open & Visualize". |
| **Knowledge Products (2026-09-20)** | "Knowledge Profile" was renamed to **Knowledge Product** and the API prefix became `/api/knowledge-products`; `PUT /{id}` became `PATCH /{id}`. Neo4j was removed, so four destinations remain (Qdrant, OpenSearch, PostgreSQL pgvector, RedisVL) and each product writes its own store names (`kp_<slug>_<id8>`), rejected on a clash with `422 DESTINATION_STORE_CONFLICT`. Manual sync was removed: a product-level poller (`src/ingestion_service/core/knowledge_sync.py`) syncs on the live or scheduled interval chosen at configuration time and reacts to MinIO add/replace/delete. New routes: `/{id}/files`, `/{id}/events` (SSE), `PATCH /{id}/destinations/{destination_id}`, `POST /{id}/pause-all`, `POST /{id}/resume-all`. See `vijay-docs/rag-ingestion-manager-docs/04_knowledge_store_page.md` |
| **Ingestion Profiles (2026-09-20)** | New reusable **Ingestion Profile**: a saved destination set plus the chunking parameters (`ingestion_profiles`, `ingestion_profile_destinations`; router prefix `/api/ingestion-profiles`). `POST /api/knowledge-products` takes an optional `ingestion_profile_id` and **copies** the profile's destinations into the product's own rows with per-product store names (`kp_<slug>_<id8>`), so editing a profile never changes an existing product; `POST /{id}/apply-profile` re-copies on demand, purges the stores it removes or changes and returns `{added, updated, removed, purged_files}`; `DELETE` answers `409 PROFILE_IN_USE` and `chunk_overlap >= chunk_size` answers `422 CHUNK_OVERLAP_TOO_LARGE`. The fanout now chunks each source page (`_resolve_chunking` / `_chunk_pages`) and writes one document per chunk with `chunk_index`, while `pages_indexed` keeps counting source pages. The Knowledge Store create dialog lost its destination block and now asks for one profile; new page `/ingestion-profiles` between Sources and Knowledge Store. See `vijay-docs/rag-ingestion-manager-docs/06_ingestion_profiles_page.md` |
| **Ingestion modality & fanout internals (2026-09-20)** | An Ingestion Profile now carries `modality_mode` (`text` or `text_images`), `text_embedding_model`, `caption_model` and `image_min_pixels`. `text` reads selectable text and tables only. `text_images` sends each embedded PDF figure to a vision model. The vision model returns one caption, which the fanout stores as normal text. Every destination and the existing text query path then find it. OCR is not implemented. The fanout embeds each chunk once per tick. It takes the vector dimension from the model output, and it rejects a batch that mixes vector lengths. A product stores a `pipeline_fingerprint` of chunk size, overlap, modality, models and threshold, and `apply-profile` purges and re-syncs every destination when that hash changes. `sync_knowledge_product()` holds a cross-process Redis lock `knowledge:sync:lock:<product_id>` with a 900-second TTL. The API poller and the pathway worker could otherwise fan out the same file. Above 2000 dimensions pgvector skips its HNSW index and searches exactly. See `vijay-docs/rag-ingestion-manager-docs/05_document_upload_page.md` and `06_ingestion_profiles_page.md` |
| **Profile editor defaults (2026-09-21)** | Every destination default is the value this deployment should start with, and each hint says so: `hnsw_m` 16 and `hnsw_ef_construct` 100 are the Qdrant defaults, `bm25_k1` 1.2 and `bm25_b` 0.75 are the OpenSearch defaults, and `number_of_replicas` 0 suits the single-node OpenSearch cluster. `summary_model` was `gpt-4o-mini`, which the proxy does not serve, so it now comes from `SUMMARY_MODEL` and defaults to `Gpt-oss-20b`. The `litellm-models` fallback chat list no longer offers the two unserved names. Numeric destination fields carry `step="any"`, because the HTML default of 1 made the browser refuse a decimal value such as BM25 k1 1.2 on submit with "the nearest values are 1 and 2" |
| **Chunk strategies (2026-09-21)** | An Ingestion Profile gained `chunk_strategy`, a select of seven. `recursive` is the default and is the algorithm that shipped first, kept byte-identical. `fixed` cuts a hard window. `sentence` packs whole sentences. `section` stores one chunk per heading or paragraph. `layout` uses the PDF's own layout blocks. `context_aware` embeds each page's sentences in one batch call and starts a new chunk at a topic shift. `parent_child` stores a large parent plus small children that name it. The strategy is part of `pipeline_fingerprint`, so Apply Profile purges and re-syncs when it changes. See `vijay-docs/rag-ingestion-manager-docs/06_ingestion_profiles_page.md` |
| **Assistant pipelines (2026-09-21)** | A pipeline can now be a **chat assistant**. The `Pipelines` page creates one from seven fields plus a Model settings fieldset (11 controls in all): an internal name, a description, one **Knowledge Product**, a **RAG Strategy** that the product's enabled destinations can serve, one **Chat Model**, and an optional **Prompt Template** and **Guardrails Config**. The record gained `slug`, `chat_model`, `prompt_template_id` and `guardrails_config_id`, and `qdrant_collection` became nullable, because an assistant owns no documents and reads the product's stores. Migration `011_assistant_pipeline` makes the change and extends the `rag_strategy` enum with `vector`, `lexical`, `relational`; `hybrid` now also means Qdrant dense fused with OpenSearch BM25. The new route `GET /api/pipelines/by-slug/{slug}` is declared before `/{pipeline_id}`, and `_pipeline_to_dict` now returns the nested `knowledge_product` with its destinations, so one call answers both "how do I reach this assistant" and "what does it read". See `vijay-docs/rag-retrieval-chat-manager-docs/02_rag_pipelines_page.md` |
| **Assistant endpoints (2026-09-21)** | Seven routes on the retrieval API, addressed by slug rather than UUID: `GET /api/assistants/{slug}`, `POST /api/assistants/{slug}/chat`, `POST /api/assistants/{slug}/chat/stream`, `POST /v1/assistants/{slug}/chat/completions`, and the three session routes `GET /api/assistants/{slug}/sessions/{session_id}`, `DELETE /api/assistants/{slug}/sessions/{session_id}` (204) and `POST /api/assistants/{slug}/sessions/{session_id}/close`. The OpenAI-compatible route lets an OpenAI SDK client point `base_url` at `http://127.0.0.1:8001/v1/assistants/{slug}` with no adapter code. The chat routes delegate to the existing `/chat` and `/chat/stream` handlers, so guardrails, retrieval, rerank, generation, persistence and metrics are reused. New readers: OpenSearch BM25 (`vector_core/lexical.py`), pgvector (`vector_core/relational.py`) and reciprocal rank fusion at `k = 60` on `(source_id, file_key, page_index, chunk_index)`. See `vijay-docs/rag-retrieval-chat-manager-docs/14_assistant_pipelines_and_endpoints.md` |
| **Additional routes (2026-09)** | Routes added to the retrieval API since the assistant work and absent from the rows above: `POST /chat/sessions/{session_id}/close`, `POST /evaluate/datasets/huggingface` (no seed, so each run samples fresh) and `POST /guardrails-evaluate/datasets/seed`. |
| **Prompt templates (2026-09-21)** | New table `prompt_templates` (retrieval Alembic revision `003`), with CRUD on `/prompt-templates` and a duplicate name answered by `409 PROMPT_TEMPLATE_NAME_TAKEN`. The migration seeds one `Default RAG` row holding the text of `RAG_SYSTEM_PROMPT`. A template is now the assistant's **system message**: `build_rag_prompt()` takes an optional `system_prompt` and falls back to `RAG_SYSTEM_PROMPT`. The retrieved passages and the question keep their user-message shape, so there are no `{context}` or `{question}` placeholders. This replaces the old Prompts page, which wrote catalog overrides to a temporary directory that nothing read. See `vijay-docs/rag-retrieval-chat-manager-docs/04_prompts_management_page.md` |
| **Chat and streaming repairs (2026-09-21)** | `POST /chat/stream` answered `500` on every request: it imported `rag_core.query_router`, a module that never existed, and called `RAGPipeline.stream_chat_self_corrective`, which was never written. Both are gone. `StreamEvent`, `RAGPipeline.stream_chat()` and `Generator.generate_stream()` now exist and stream real token deltas. Guardrails never blocked a turn, because the config stores `ban_list` while the guardrails service names its guard `ban-list`; every check returned 404 and the client read a non-200 as "passed". The client now maps the underscore to a hyphen. `Settings.embedding_model` defaulted to `nvidia-embed-passage`, which the proxy does not serve; it is now `nvidia-embed-textonly`. The `Router`, `Classifier`, `RAG Mode` and `Max Loops` controls left the Chat page, because the query router and self-corrective RAG are not implemented |
| **Retrieval runtime (2026-09-20)** | The retrieval stack now runs on the host end to end. Five defects blocked it, all fixed: `libs/vector-core/pyproject.toml` resolved `platform-common` three levels up instead of four, so `uv sync` failed outside Docker; `rag_db.migrate` used `parents[1]` (`libs/database/src`, no `alembic.ini`) so migrations could not run on the host; four `DELETE` routes annotated `-> Response` without importing it, which made `/openapi.json` return 500 with a Pydantic `class-not-fully-defined` error; `routes/prompts.py` called `has_override`/`write_override`/`clear_override` with a filename alone instead of `(package, name)`, so `GET /prompts` returned 500; and `get_engine()` built a new engine per request, leaking a pool until Postgres refused connections — that one surfaced in the browser as a CORS error, because a 500 from Starlette's error middleware carries no CORS headers. `get_engine()` is now `@lru_cache`d per URL. Pre-existing: 20 of 52 retrieval unit tests fail (`test_dataset_upload.py` expects a 20-item golden dataset, the committed file has 5; `test_stats.py` fails only in a full-suite run). See `vijay-docs/rag-retrieval-chat-manager-docs/overall-rag-retrieval-chat-manager.md` |
| **Guardrails tables (2026-09-20)** | New Alembic revision `002_guardrails_tables` creates the six `guardrails_*` tables. `001_initial_schema` predates the guardrails models and `alembic/env.py` imported only `chat` and `evaluation`, so the tables never existed and all three Guardrails pages failed with "relation does not exist". The revision builds them from `Base.metadata`, so the columns cannot drift from the models |
| **Retrieval Knowledge Store (2026-09-20)** | The retrieval manager's Knowledge Store is now a **view-only mirror** of the ingestion manager's Knowledge Products. Create, edit, delete and every pause or configure control are gone; the page lists products with a derived **RUNNING / PAUSED** badge per product and per destination, a `View` button and a `Refresh`. New read-only detail route `/knowledge-store/:id` with the live fanout timeline (SSE), the ingested-file ledger, the 5 s poll and the destination store inspector. `Refresh` is the manual sync: the ingestion API has no sync route by design, so the page sends `PATCH {}`, which re-registers the product poller and fires one immediate sync. The page re-reads on every route entry (`AppLayout` keeps pages mounted, so the page watches `location.pathname` rather than mounting). The timeline, visualizers and SSE hook were ported byte-identical from the ingestion manager; `api.ts` gained the read-only bindings and lost the three orphaned write functions. See `vijay-docs/rag-retrieval-chat-manager-docs/11_knowledge_store_page.md` |
| **Evaluation rework (2026-09-27)** | Offline Evaluation accepts a JSON **and** a CSV golden dataset, stores per-item retrieval, rerank and generation metrics, and takes an optional `judge_model` per run. `k_values` is accepted but unused, and the retrieval metrics are computed in-process rather than by a judge. See `vijay-docs/rag-retrieval-chat-manager-docs/06_offline_evaluation_page.md` |
| **Wider retrieval strategies (2026-09-27)** | SQL search was replaced by `self_rag` and `corrective`, so a pipeline's strategy selects the store to read and the pattern to grade with. The fanout writes to the same Qdrant the assistant reads |
| **RAG triad and stage attribution (2026-09-28)** | `context_relevance`, `response_groundedness` and `answer_relevancy` are stored per row, and `diagnose()` turns them into a named failing stage. A partial triad is never reported as healthy |
| **One Qdrant for both projects (2026-09-29)** | The two projects were consolidated onto the single Qdrant on `6333`, which holds the scraper's `scrape_embeddings` and every `kp_*` collection. `QDRANT_KP_URL` mirrors `QDRANT_URL`; an empty value falls back silently |
| **Guard catalog cut to three (2026-09-29)** | `guardrails-service` exposes `ban_list`, `detect_pii` and `local/toxic_language` only. The eleven unused Guardrails Hub packages stay declared in `pyproject.toml` |
| **Host run documented (2026-09-29)** | `backend/.env` holds the container names and `backend/.env.local` holds the host values. pydantic-settings reads them in that order, so the later file wins and a real environment variable beats both. `scripts/dev.sh` runs each app on the host with its dependencies in Docker |
| **Per-source webscraping (2026-09-30)** | A source carries a **Web scraping** switch with a max depth and a max page count. While it is on, every `*_scrp.txt` object in that bucket is read as a list of URLs and one `.md` per crawled page is written back beside a full-page `.png`. The scraper gained `embedding_source: "none"` and three page-artifact routes; the fanout skips the manifests and the screenshots. The web scraper also moved to a compose `scraper` profile and now runs from the host |
| **Ingestion pages renamed (2026-10-01)** | `/sources` is **Knowledge Fabric**, `/browse` is **Fabric Viewer**, `/knowledge-store` is **Knowledge Hub**. Routes, components and doc file names are unchanged. The four destinations now lead with the type and name the engine beside it: *Dense Vector Store (Qdrant)*, *Sparse Vector Store (OpenSearch)*, *Relational Chunk Store (Postgres)*, *Cache Store (Redis VL)* |
| **Store inspector, NUL text and batch size (2026-10-02)** | The visualizer modal reads a store once when it opens or the tab changes, and only on **Refresh Live Data**; it used to refetch on every 5-second poll of the page behind it. `FilePage.__post_init__` strips NUL bytes, which PostgreSQL rejects and which failed a whole relational insert. The shared embedding client sends at most 256 inputs per request, the NVIDIA NIM limit, instead of falling back to FastEmbed. A host run also carried `OTEL_TRACING_ENABLED=false` in `.env.local`, which silenced both trace modes with no error anywhere |
| **Eight chunk strategies and page-image mode (2026-10-08)** | `GET /api/ingestion-profiles/chunk-strategies` serves the strategy catalogue, so the profile form holds no strategy knowledge. An Ingestion Profile now stores `chunk_config` (one JSON column for the selected strategy's settings) and `image_embedding_model` (default `nvidia-embed-multimodal`), and no longer stores `caption_model` or `image_min_pixels` (migration `016_chunk_config_page_images`). The chunker offers the eight strategies — Recursive, Fixed-Size, Structure-Aware, Semantic, Parent-Child, Contextual, Page-Level and Sentence-Window — and reads each one's settings from `chunk_config`. `text_images` renders every document page to a PNG at 150 dpi, stores it under `_pages/`, and writes one record per page embedded from the image, with the page text riding along. The caption path and its `image_min_pixels` filter are removed, and `CAPTION_MODEL_REQUIRED` is replaced by `IMAGE_EMBEDDING_MODEL_REQUIRED`. The sync summary key `images_skipped` is now `pages_without_image`. See `vijay-docs/rag-ingestion-manager-docs/06_ingestion_profiles_page.md` |
| **Destination config** | New `backend/apps/api/routes/knowledge_destination_schemas.py` supplies typed field schemas, Docker-aware defaults, `build_destination_types()`, `merge_destination_config()` and `normalize_destination_payload()`; surfaced by `GET /api/knowledge-products/destinations/options` and consumed by the new `frontend/src/components/DestinationConfigFields.tsx` |
| **LiteLLM models** | `GET /api/knowledge-products/config/litellm-models?model_kind=all\|embedding\|rerank\|chat\|vision\|sparse` reads the LiteLLM proxy's **`/v1/model/info`** and classifies every model by the `model_info.mode` the proxy reports: `embedding` → embedding, `rerank` → rerank, `chat` and `completion` → chat, `vision` → vision. An entry with no mode, or a mode outside that set, is skipped and logged. `sparse` is not a proxy concept, so it always comes from `SPARSE_EMBEDDING_MODEL`. The proxy result is cached for 60 s. Falls back to the models the environment names when the proxy is unreachable, and reports `default_embedding_model` and `default_image_embedding_model` so the editor defaults to the models this deployment serves. The earlier version read `/v1/models` and guessed the kind from the model name, which put `All-MiniLM-L6-v2` and `nvidia-rerank` in the chat list |
| **Fanout** | Per-file parallel destination writes with `asyncio.gather(..., return_exceptions=True)`, per-destination error isolation, ETag/size change detection, per-product store names, and purge helpers for Qdrant, OpenSearch, PostgreSQL and RedisVL. The embedding call the fanout makes sends at most `_MAX_EMBED_BATCH = 256` inputs per request (`shared-libs/platform-common/src/platform_common/embeddings/dense.py`), which is the NVIDIA NIM limit; a larger file is split in order rather than failed |
| **Parsing & chunking** | `page_yielder.py` streams PDF (PyMuPDF), DOCX, CSV, JSON, Markdown and text pages; `FilePage.__post_init__` strips NUL bytes from a page's text before any chunker or writer sees it; chunking selects one of eight strategies and reads its settings from `chunk_config`, with the window defaulting to `chunk_size=1000` / `chunk_overlap=120` |
| **Qdrant** | The dimension comes from the embedding model output, not from a `vector_size` setting. The collection name is per product (`kp_<slug>_<id8>`). `qdrant_store.py` raises when a stored vector size disagrees with the derived dimension, because recreation deletes every point. `ensure_collection()` also accepts optional `hnsw_m` and `hnsw_ef_construct` tuning |
| **Auth** | `make_verify_api_key` accepts `X-API-Key` or the `api_key` query parameter for browser fetches that cannot set headers |
| **Frontend** | Ingestion nav exposes 5 entries: Overview / **Fabric Viewer** / **Knowledge Fabric** / Ingestion Profiles / **Knowledge Hub** (the three renamed on 2026-10-01), with pages mounted persistently in `AppLayout.tsx` (the Upload item was removed 2026-09-20). Retrieval nav exposes 10 items (Overview, Knowledge Store, Pipelines, Chat, Prompts, Real Time Monitoring, Offline Evaluation, Guard Config, Guard Traces, Guard Evaluation). The Tracking item was removed on 2026-09-23. The retrieval app mounts 18 routes in all: the 10 nav entries plus `/browse`, `/browse/:name`, `/browse/:name/view/:fileId`, `/upload`, `/sources`, `/sources/:id`, `/knowledge-store/:id` and `/golden-evaluations/runs/:id` |
| **Docker** | The ingestion `docker-compose.yaml` and both Dockerfiles build from the monorepo root (`rag-ingestion-manager/docker-compose.yaml:5-6`, `backend/Dockerfile:6-16`, `rag-retrieval-chat-manager/backend/Dockerfile:13-17`). The retrieval `backend/docker-compose.yaml` builds from its own `rag-retrieval-chat-manager/backend/Dockerfile` against the monorepo root, and the retrieval stack runs as its own compose project with 4 services (see §4). The guardrails service and the web-scrapper are declared in the ingestion compose file and start from there |
| **Settings** | Centralized OpenSearch URL in `settings.py`; the legacy `neo4j_*` settings stay declared but no destination reads them; retrieval defaults (port, models, limits) live in `rag_shared/config.py` |
| **Verification** | E2E scripts that exist: `scripts/e2e_knowledge_fanout.py` (21 checks), `scripts/e2e_knowledge_pause.py` (14 checks), `scripts/e2e_ingestion_profiles.py` (50 checks), `scripts/e2e_ingestion_modality.py` (text mode and the page-image mode) and `scripts/e2e_chunk_strategies.py` (walks section, parent_child, fixed, context_aware, page_level and sentence_window); ingestion unit tests under `backend/tests/` for the page yielder (including the NUL strip and the page raster), the page-image embedding failure, the fanout payload, the destination schemas, the product files ledger, the connector config validation, profile chunking, the chunk strategies, the modality resolvers and the source webscrape; shared-library tests under `shared-libs/platform-common/tests/` for the SSRF guard and the embedding batch cap; retrieval unit suite under `tests/unit/` plus the Qdrant integration test. The retrieval side also has `scripts/e2e_assistant_pipelines.py`, `e2e_guardrails.py`, `e2e_kp_contract.py`, `e2e_chat_session_traces.py`, `e2e_session_memory.py`, `e2e_offline_eval_csv.py` and `check_deps.py`. No suite was re-run for this documentation pass |

All systems, API routes, models, and interactive visualizers are documented across `vijay-docs/`.
