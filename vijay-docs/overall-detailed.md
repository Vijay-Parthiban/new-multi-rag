# End-to-End Architecture & Operational Manual — new-multi-rag

**Last updated:** 2026-09-20

## 1. System Architecture Overview
The **`new-multi-rag`** platform is an enterprise-grade, distributed Retrieval-Augmented Generation (RAG) system composed of two decoupled and complementary subsystems:

1. **`rag-ingestion-manager`** (Frontend: Port `5173`, Backend: published on host port `8007` / container port `8000`):
   - Ingestion perimeter. Two bucket source types are creatable: **Apache NiFi Connector Source** and **Manual Upload Source** (`backend/apps/api/routes/sources.py:277-382`). The connector catalogue is NiFi-only and holds exactly three ids — `google_drive`, `s3`, `azure_blob` (`sources.py:35-41`); connector pulls are executed by the NiFi-based engine (`src/ingestion_service/core/nifi_sync.py`). Legacy connector rows for other ids still resolve and can be edited, but no new one can be attached.
   - Each connector chooses **live** polling (fixed 3-second loop) or **scheduled** polling with an interval in **seconds or minutes** (`sync_interval_seconds`, added 2026-09-20, takes priority over `sync_interval_minutes`).
   - Document staging, change detection over the object ETag and size (`src/ingestion_service/core/universal_fanout.py`), multi-format parsing and recursive text chunking.
   - Every source owns a MinIO bucket named `<MINIO_BUCKET_PREFIX>-<source name>-<source id[:8]>` (default prefix `source`, `src/shared/config/settings.py:44`, `backend/apps/api/routes/sources.py:255-259`); legacy local-filesystem sources live under `storage/local_sources/<folder>`. Deleting a source empties and removes its bucket.
   - **Universal 4-Destination Fanout Engine** (`src/ingestion_service/core/universal_fanout.py`) syncing documents into 4 destination types, written **in parallel per file** via `asyncio.gather(..., return_exceptions=True)` with per-destination error isolation: **Qdrant Vector DB**, **OpenSearch BM25**, **PostgreSQL pgvector**, and **RedisVL Semantic Cache** (`backend/apps/api/routes/knowledge_destination_schemas.py`). Each Knowledge Product writes to its own store names (`kp_<slug>_<id8>`).
   - **Product lifecycle purge**: deleting a Knowledge Product triggers `purge_knowledge_product()`; a changed or deleted file is purged from every destination that holds it, keyed on `(source_id, file_key)` (`universal_fanout.py`, `backend/apps/api/routes/knowledge_products.py`).
   - **Multi-format parsing** via `page_yielder.py`, which yields one page at a time: PDF (PyMuPDF), DOCX, CSV, JSON, Markdown/plain text, with a UTF-8 fallback for unknown types (`core/page_yielder.py:21-56`). Chunking is word-based with pipeline defaults `chunk_size=1000` / `chunk_overlap=120` (`core/utils/text_splitter.py:4`, `src/shared/db/models.py:276-277`).
   - **Typed destination configuration**: `GET /api/knowledge-products/destinations/options` returns Docker-aware defaults, per-field schemas and `namespace_fields` (`routes/knowledge_destination_schemas.py`), and `GET /api/knowledge-products/config/litellm-models` lists models from the LiteLLM proxy with an environment fallback (`routes/knowledge_products.py`).
   - **Interactive Multi-Destination Visualizers** via `GET /api/knowledge-products/{product_id}/inspect/{destination_type}` (four destination branches).
   - **Uploads happen on the Sources page.** The standalone Upload page (`/upload`) was removed on 2026-09-20. Create a Manual Upload Source, or use the **Upload Files** action on a manual source, to write files into that source's MinIO bucket. The chunked-upload API (`/api/uploads/*`) remains but has no UI caller.

2. **`rag-retrieval-chat-manager`** (Frontend: Port `5174`, Backend: Port `8001`):
   - Multi-stage retrieval and conversational intelligence gateway (`apps/rag-api/src/rag_api/main.py`, `create_app()`).
   - Hybrid dense/sparse retrieval: one Qdrant query with dense `prefetch` plus sparse `Qdrant/bm25` prefetch (IDF modifier) fused with Reciprocal Rank Fusion (`libs/vector-core/src/vector_core/search.py:17-33`, `shared-libs/platform-common/src/platform_common/vector/qdrant_store.py:225-242`). Defaults: `default_retrieval_mode=hybrid`, `retrieve_limit=20` (`libs/shared/src/rag_shared/config.py:29-30`).
   - Reranking through the LiteLLM `POST /v1/rerank` endpoint (`libs/reranker-core/src/reranker_core/litellm_reranker.py`), default model `nvidia-rerank`, `rerank_top_k=5` (`config.py:32-34`); `NoopReranker` when disabled.
   - Context-grounded generation over LiteLLM with streaming SSE, vision multimodal inputs and dynamic prompt templating. Defaults: `chat_model=llama-3.3-70b-versatile`, `vision_model=groq-vision`, `fusion_model=llama-3.3-70b-versatile` (`config.py:36-38`).
   - Safety guardrails delegate to the standalone `guardrails-service` (Guardrails AI) over HTTP with guards `ban-list`, `pii-check` (DetectPII / Presidio entities) and `toxic-language` (`guardrails-service/server.py:29-38`, `guardrails-service/config.py:130-139`); the shared HTTP client defaults to `http://localhost:8002` (`libs/shared/src/rag_shared/guardrails_client.py:13`) while the ingestion compose file publishes the service on host port `18000` (`rag-ingestion-manager/docker-compose.yaml:313-314`). Chat requests optionally bind a stored guardrails config (`frontend/src/pages/ChatPage.tsx:382`).
   - Continuous observability through the OpenTelemetry collector in `otel/` (Langfuse, Arize AX, Grafana Cloud exporters), and Ragas evaluation both online (per chat message) and offline (golden datasets), with the RQ `eval` queue on Redis (`config.py:16-18`).

---

## 2. End-to-End Data & Execution Lifecycle

```
========================================================================================================================
                                             PHASE 1: DATA INGESTION & 4-DESTINATION FANOUT
========================================================================================================================
[ External Sources / Connectors ]  --->  [ MinIO Object Store ]  --->  [ Ingestion Backend :8007 ]
(Google Drive, S3, Azure, SFTP,          (one bucket per source:      - Extract & Parse (PDF/DOCX/CSV/JSON/MD/TXT)
 Confluence, Manual upload, NiFi engine)  source-<name>-<id8>)        - ETag + Size Change Detection
                                                                      - Word-based Chunking (1000 / overlap 120)
                                                                      - Dense Embeddings via LiteLLM
                                                                        (nvidia-embed-passage default)
                                                                                    |
                                                                                    v
                                                                    [ Universal Fanout Engine ]
                                                                      (universal_fanout.py)
                                                       asyncio.gather per file, per-destination isolation
                                                                                    |
            +-----------------------+-----------------------+-----------------------+-----------------------+
            |                       |                       |                       |
            v                       v                       v                       v
    +---------------+       +---------------+       +---------------+       +---------------+
    | 1. Qdrant     |       | 2. OpenSearch |       | 3. PostgreSQL |       | 4. RedisVL    |
    | Vector DB     |       | BM25 Lexical  |       | pgvector      |       | Chunk Cache   |
    | (dense HNSW)  |       | (inverted)    |       | Relational    |       | (+ optional   |
    |               |       |               |       | Chunks        |       | RAPTOR summaries)|
    +---------------+       +---------------+       +---------------+       +---------------+

========================================================================================================================
                                           PHASE 2: RAG RETRIEVAL, SYNTHESIS & EVALUATION
========================================================================================================================
[ User / Chat Client ] -> rag-retrieval-chat-manager :8001
        |
        v
[ Guardrails Check ] (guardrails-service -> POST /parse/{guard_name})
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
| **Guardrails Service** | `18000` (host) → `8000` (container) | Guardrails AI server exposing `POST /parse/{guard_name}` for `ban-list`, `pii-check`, `toxic-language` (`docker-compose.yaml:313-314`, `guardrails-service/Dockerfile:59`) |
| **Web-Scrapper API** | `8000` | Crawl/scrape service from `web-scrapper-workspace`; shares Postgres, Redis and Qdrant (`docker-compose.yaml:142`) |
| **LiteLLM proxy** | `4000` | External (host-run) OpenAI-compatible proxy for embeddings, rerank, chat and vision (`settings.py:21`, `rag_shared/config.py:24`) |
| **MinIO Object Storage** | `9000` / `9001` | Raw document binaries, one bucket per source named `source-<name>-<id[:8]>` (`docker-compose.yaml:76-77`, `routes/sources.py:259`) & console |
| **Qdrant Vector DB** | `6333` | Named dense + sparse vectors. Destination default `vector_size=2048`; each Knowledge Product writes its own collection `kp_<slug>_<id8>` for fanout (`knowledge_destination_schemas.py`); retrieval reads `scrape_embeddings` (`rag_shared/config.py:22`); collection is recreated when the stored vector size mismatches the configured size (`platform_common/vector/qdrant_store.py:82-90`). The local ingestion `.env` and the E2E script point at `http://localhost:6335` (`rag-ingestion-manager/backend/.env`, `backend/scripts/e2e_knowledge_fanout.py`) |
| **OpenSearch** | `9200` | Full-text BM25 lexical inverted index. Each Knowledge Product writes its own index `kp_<slug>_<id8>` (`knowledge_destination_schemas.py`); performance analyzer on `9600`, dashboards on `5601` (`docker-compose.yaml:330-331,342`) |
| **Neo4j Graph DB** | `7474` / `7687` | The compose service and its `neo4j_data` volume stay declared, but the `graph_neo4j` destination was removed on 2026-09-20, so no destination reads or writes Neo4j. `scripts/purge_neo4j_legacy.py` deletes the previously written `Chunk`/`Document`/`Entity` nodes. |
| **PostgreSQL DB** | `5432` | Two databases: `ingestion` (ingestion API metadata, user/password `ingestion`) and `rag` (retrieval: chat, evaluation and guardrails tables in `libs/database/src/rag_db/models/`). Each Knowledge Product gets its own pgvector schema `kp_<slug>_<id8>` with a `chunks` table (`universal_fanout.py`). The local ingestion `.env` overrides the API database with SQLite (`sqlite+aiosqlite:///storage/ingestion.db`) |
| **Redis / RedisVL** | `6379` | Ingestion RQ queues `file_manager:jobs`, `ingestion:pipeline:jobs`, `ingestion:sync:jobs` (`settings.py:12-14`); RedisVL sink writes `<prefix>:<source_id>:<file_key>:<page>` keys with a 24 h TTL, where the prefix is the product's `kp:<slug>:<id8>` (`knowledge_destination_schemas.py`, `universal_fanout.py`); retrieval RQ `eval` queue (`rag_shared/config.py:18`) |
| **OpenTelemetry Collector** | `4317` (gRPC) / `4318` (HTTP) | Receives OTLP traces/metrics/logs and exports to Langfuse, Arize AX and Grafana Cloud (`docker-compose.yaml:198-199`, `otel/otel-collector-config.yaml:76-96`) |

---

## 4. Operational Runbook & Verification

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

**Retrieval Chat Manager Backend** (module `rag_api.main:app`; the repo script reads `API_HOST`/`API_PORT` and defaults to `8001`, which is also `Settings.api_port`):

```bash
cd rag-retrieval-chat-manager/backend
sh scripts/run-api.sh          # exec uvicorn rag_api.main:app --host 0.0.0.0 --port 8001
```

**Retrieval Chat Manager Frontend** (the Vite config already fixes port `5174`):

```bash
cd rag-retrieval-chat-manager/frontend
npm run dev
```

**Retrieval Chat Manager worker / migrations**:

```bash
cd rag-retrieval-chat-manager/backend
sh scripts/run-migrate.sh      # rag-db-migrate (Alembic to head)
sh scripts/run-worker.sh       # rq worker eval --url $REDIS_URL
```

**Guardrails service** (published on `18000` by the ingestion compose file):

```bash
cd rag-ingestion-manager
docker compose up -d guardrails-service
```

Verification assets that exist in the tree:
- Ingestion E2E fanout scripts: `rag-ingestion-manager/backend/scripts/e2e_knowledge_fanout.py` and `rag-ingestion-manager/backend/scripts/e2e_knowledge_pause.py`
- Legacy Neo4j purge script: `rag-ingestion-manager/backend/scripts/purge_neo4j_legacy.py`
- Ingestion unit tests: `rag-ingestion-manager/backend/tests/test_page_yielder.py`, `test_fanout_payload.py`, `test_knowledge_destination_schemas.py`, `test_knowledge_product_files.py`
- Retrieval unit tests: `rag-retrieval-chat-manager/backend/tests/unit/` (16 modules, run with `uv run pytest tests/unit -v`); integration test `tests/integration/test_qdrant_retrieve.py` (requires a reachable Qdrant)

---

## 5. Shared Library & Cross-Service Contracts

`shared-libs/platform-common/` (`platform_common`) is the shared integration layer used by ingestion, retrieval and the web-scrapper:

| Module | Role |
|---|---|
| `platform_common/auth.py` | API key verification via `X-API-Key` header **or** `api_key` query parameter (`:12`, `:32`); no-op when the configured key is empty, `/health`, `/docs`, `/openapi.json` and `/redoc` bypass auth (`:11`). Both backends build their dependency with `make_verify_api_key` (`src/shared/auth.py:8`, `rag_shared/auth.py:8`) |
| `platform_common/vector/qdrant_store.py` | Qdrant collection management; recreates the collection when the stored vector size mismatches the configured size (`:82-90`) |
| `platform_common/vector/hit_mapper.py` | Retrieval payload contract: `source_type`, `source_id`, `source_locator`, `content`, `chunk_index`, `title`, `file_name`, `page_index` (`:20-48`) |
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

Ingestion fanout payloads are built by `_build_fanout_payload()` (`universal_fanout.py`) with the `knowledge_product_id` key, so retrieval and visualizers stay aligned.

**Retrieval Knowledge Store path.** The retrieval backend only *proxies* knowledge products over HTTP to the ingestion manager: `apps/rag-api/src/rag_api/routes/knowledge.py` mounts `APIRouter(prefix="/api/knowledge-products")` and every route forwards to `settings.ingestion_service_url or "http://localhost:8007"`, returning `503` when the ingestion service is unreachable. The proxies are list/create/get/update/delete (update is `PATCH`) and `POST /{id}/test-connection`; the manual sync proxy is gone. There is no ingestion database access from the retrieval side. The retrieval frontend's Knowledge Store page calls the ingestion API directly, since its API client resolves `VITE_API_URL` (default `http://localhost:8007`, `frontend/src/api.ts:3`) through `apiFetch` (`frontend/src/api.ts:375-429`).

---

## 6. Recent Platform Updates (2026-09)

| Area | Change |
|---|---|
| **Sources page (2026-09-20)** | Upload page removed. Two bucket source types only: **Apache NiFi Connector Source** and **Manual Upload Source**. Connector catalogue narrowed to three NiFi-only ids (`google_drive`, `s3`, `azure_blob`); one source can hold many connectors. Each connector picks live polling or a scheduled interval in seconds or minutes. Source delete asks in an in-app confirmation dialog showing the bucket and object count, then empties and removes the MinIO bucket. See `vijay-docs/rag-ingestion-manager-docs/03_data_sources_page.md` |
| **Sources page pause (2026-09-20)** | The manual **Sync All Connectors** / **Sync Now** buttons are gone. Polling is automatic from the moment a connector is saved; the UI now exposes **Pause All Connectors** / **Pause** (and Resume) that flip `SourceConnector.enabled`. `register_source_poller` derives mode and interval from the enabled connectors instead of the source-level default, and stops the poller when every connector is paused. Connector buckets show no file actions; manual buckets keep Delete but lose "Open & Visualize". |
| **Knowledge Products (2026-09-20)** | "Knowledge Profile" was renamed to **Knowledge Product** and the API prefix became `/api/knowledge-products`; `PUT /{id}` became `PATCH /{id}`. Neo4j was removed, so four destinations remain (Qdrant, OpenSearch, PostgreSQL pgvector, RedisVL) and each product writes its own store names (`kp_<slug>_<id8>`), rejected on a clash with `422 DESTINATION_STORE_CONFLICT`. Manual sync was removed: a product-level poller (`src/ingestion_service/core/knowledge_sync.py`) syncs on the live or scheduled interval chosen at configuration time and reacts to MinIO add/replace/delete. New routes: `/{id}/files`, `/{id}/events` (SSE), `PATCH /{id}/destinations/{destination_id}`, `POST /{id}/pause-all`, `POST /{id}/resume-all`. See `vijay-docs/rag-ingestion-manager-docs/04_knowledge_store_page.md` |
| **Destination config** | New `backend/apps/api/routes/knowledge_destination_schemas.py` supplies typed field schemas, Docker-aware defaults, `build_destination_types()`, `merge_destination_config()` and `normalize_destination_payload()`; surfaced by `GET /api/knowledge-products/destinations/options` and consumed by the new `frontend/src/components/DestinationConfigFields.tsx` |
| **LiteLLM models** | New `GET /api/knowledge-products/config/litellm-models?model_kind=all\|embedding\|chat\|sparse`: reads `/v1/models` from the LiteLLM proxy and falls back to `settings.unique_embedding_models` / `gpt-4o-mini`+`gpt-4o` / `Qdrant/bm25` when the proxy is unreachable |
| **Fanout** | Per-file parallel destination writes with `asyncio.gather(..., return_exceptions=True)`, per-destination error isolation, ETag/size change detection, per-product store names, and purge helpers for Qdrant, OpenSearch, PostgreSQL and RedisVL |
| **Parsing & chunking** | `page_yielder.py` streams PDF (PyMuPDF), DOCX, CSV, JSON, Markdown and text pages; chunking is word-based with defaults `chunk_size=1000` / `chunk_overlap=120` |
| **Qdrant** | Destination default `vector_size: 2048`; the collection name is per product (`kp_<slug>_<id8>`); `qdrant_store.py` recreates a collection whose stored vector size differs from the configured size |
| **Auth** | `make_verify_api_key` accepts `X-API-Key` or the `api_key` query parameter for browser fetches that cannot set headers |
| **Frontend** | Ingestion nav exposes Overview / Folders / Sources / Knowledge Store, with pages mounted persistently in `AppLayout.tsx` (the Upload item was removed 2026-09-20); retrieval nav exposes 11 items (Overview, Knowledge Store, Pipelines, Chat, Prompts, Real Time Monitoring, Offline Evaluation, Tracking, Guard Config, Guard Traces, Guard Evaluation) |
| **Docker** | The ingestion `docker-compose.yaml` and both Dockerfiles build from the monorepo root (`rag-ingestion-manager/docker-compose.yaml:5-6`, `backend/Dockerfile:6-16`, `rag-retrieval-chat-manager/backend/Dockerfile:13-17`). The retrieval `backend/docker-compose.yaml:5,16,37` still references `rag-app-workspace/Dockerfile`, a path that no longer exists in the tree — the usable file is `rag-retrieval-chat-manager/backend/Dockerfile` |
| **Settings** | Centralized OpenSearch URL in `settings.py`; the legacy `neo4j_*` settings stay declared but no destination reads them; retrieval defaults (port, models, limits) live in `rag_shared/config.py` |
| **Verification** | E2E scripts `scripts/e2e_knowledge_fanout.py` and `scripts/e2e_knowledge_pause.py`; unit tests for the page yielder, the fanout payload, the destination schemas, the product poller intervals and the connector config validation (`pytest tests -q`, 23 passing); retrieval unit suite under `tests/unit/` plus the Qdrant integration test |

All systems, API routes, models, and interactive visualizers are documented across `vijay-docs/`.
