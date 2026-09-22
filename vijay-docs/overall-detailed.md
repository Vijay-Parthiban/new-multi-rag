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
   - **Ingestion modality and captions**: an Ingestion Profile carries `modality_mode`, `text_embedding_model`, `caption_model` and `image_min_pixels` (`src/shared/db/models.py`). `text` (default) reads selectable text and tables only, and ignores images. `text_images` sends each embedded PDF figure to a vision model, which writes one caption. The fanout stores that caption as normal text, so every enabled destination and the text query path find it. Figures smaller than `image_min_pixels` (default 10000) are skipped, so a logo or rule never becomes a chunk. Extraction reads embedded image XObjects and does not render pages. **OCR is not implemented.** A caption that fails is dropped and counted in `images_skipped`.
   - **Derived vector dimension**: the profile no longer configures `vector_size`. The fanout embeds each chunk once per tick and takes the dimension from the embedding model output. Every vector destination reuses that one vector. The fanout rejects a batch whose vectors have mixed lengths, because a failed proxy call can fall back to a local 384-dimension model. It refuses to recreate an existing Qdrant collection whose dimension disagrees, because recreation deletes every point.
   - **One sync per Knowledge Product**: `sync_knowledge_product()` takes a cross-process Redis lock `knowledge:sync:lock:<product_id>` with a 900-second TTL. The lock exists because the API host polls the product while the pathway worker kicks the same product after a source change. Both could fan out the same file, and three stores then held duplicate documents. The lock releases with a compare-and-delete script, so it cannot delete another holder's lock.
   - **Multi-format parsing** via `page_yielder.py`, which yields one page at a time: PDF (PyMuPDF), DOCX, CSV, JSON, Markdown/plain text, with a UTF-8 fallback for unknown types (`core/page_yielder.py:21-56`). Chunking is word-based with pipeline defaults `chunk_size=1000` / `chunk_overlap=120` (`core/utils/text_splitter.py:4`, `src/shared/db/models.py:276-277`).
   - **Typed destination configuration**: `GET /api/knowledge-products/destinations/options` returns Docker-aware defaults, per-field schemas and `namespace_fields` (`routes/knowledge_destination_schemas.py`), and `GET /api/knowledge-products/config/litellm-models` lists models from the LiteLLM proxy with an environment fallback (`routes/knowledge_products.py`).
   - **Interactive Multi-Destination Visualizers** via `GET /api/knowledge-products/{product_id}/inspect/{destination_type}` (four destination branches).
   - **Uploads happen on the Sources page.** The standalone Upload page (`/upload`) was removed on 2026-09-20. Create a Manual Upload Source, or use the **Upload Files** action on a manual source, to write files into that source's MinIO bucket. The chunked-upload API (`/api/uploads/*`) remains but has no UI caller.

2. **`rag-retrieval-chat-manager`** (Frontend: Port `5174`, Backend: Port `8001`):
   - Multi-stage retrieval and conversational intelligence gateway (`apps/rag-api/src/rag_api/main.py`, `create_app()`).
   - Hybrid dense/sparse retrieval: one Qdrant query with dense `prefetch` plus sparse `Qdrant/bm25` prefetch (IDF modifier) fused with Reciprocal Rank Fusion (`libs/vector-core/src/vector_core/search.py:17-33`, `shared-libs/platform-common/src/platform_common/vector/qdrant_store.py:225-242`). Defaults: `default_retrieval_mode=hybrid`, `retrieve_limit=20` (`libs/shared/src/rag_shared/config.py:29-30`).
   - Reranking through the LiteLLM `POST /v1/rerank` endpoint (`libs/reranker-core/src/reranker_core/litellm_reranker.py`), default model `nvidia-rerank`, `rerank_top_k=5` (`config.py:32-34`); `NoopReranker` when disabled.
   - Context-grounded generation over LiteLLM with streaming SSE, vision multimodal inputs and dynamic prompt templating. Defaults: `chat_model=llama-3.3-70b-versatile`, `vision_model=groq-vision`, `fusion_model=llama-3.3-70b-versatile` (`config.py:36-38`).
   - Safety guardrails delegate to the standalone `guardrails-service` (Guardrails AI) over HTTP. The service holds the validator catalog: 16 validators, 13 of them real Hub packages installed from public PyPI as `guardrails-ai-<name>`, and three LLM judges registered as `local/toxic_language`, `local/restrict_to_topic` and `local/prompt_injection` that call the LiteLLM proxy (`guardrails-service/config.py:167`, `guardrails-service/server.py:50`). It exposes `GET /catalog`, `POST /validate`, `POST /validate-config` and `GET /health-check` (`guardrails-service/server.py:45-69`). The retrieval API proxies the catalog for the Guard Config page and validates a saved config through `POST /validate-config` before it stores it (`rag_api/routes/guardrails.py:231`). The shared HTTP client defaults to `http://localhost:18000` (`libs/shared/src/rag_shared/guardrails_client.py:65`), and the ingestion compose file publishes the service on host port `18000` (`rag-ingestion-manager/docker-compose.yaml:306-317`). Chat requests optionally bind a stored guardrails config.
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
| **Guardrails Service** | `18000` (host) → `8000` (container) | Guardrails AI service exposing `GET /catalog` for the 16 installed validators, plus `POST /validate` and `POST /validate-config` (`guardrails-service/server.py`, `docker-compose.yaml:306-317`) |
| **Web-Scrapper API** | `8000` | Crawl/scrape service from `web-scrapper-workspace`; shares Postgres, Redis and Qdrant (`docker-compose.yaml:142`) |
| **LiteLLM proxy** | `4000` | External (host-run) OpenAI-compatible proxy for embeddings, rerank, chat and vision (`settings.py:21`, `rag_shared/config.py:24`) |
| **MinIO Object Storage** | `9000` / `9001` | Raw document binaries, one bucket per source named `source-<name>-<id[:8]>` (`docker-compose.yaml:76-77`, `routes/sources.py:259`) & console |
| **Qdrant Vector DB** | `6333` and `6335` | Named dense + sparse vectors. **Two instances run side by side:** the compose service `rag-ingestion-manager-qdrant-1` publishes host `6333`, and a separately started `qdrant` container publishes host `6335`. The ingestion backend and its E2E script target **6335**, which holds the fanout collections `kp_<slug>_<id8>`; the scraper writes `scrape_embeddings` to the compose container via Docker DNS `qdrant:6333`, so the retrieval backend must read **6333** to see scraper data. The fanout takes the dimension from the embedding model output. It refuses to recreate an existing collection whose dimension disagrees, because recreation deletes every point |
| **OpenSearch** | `9200` | Full-text BM25 lexical inverted index. Each Knowledge Product writes its own index `kp_<slug>_<id8>` (`knowledge_destination_schemas.py`); performance analyzer on `9600`, dashboards on `5601` (`docker-compose.yaml:330-331,342`) |
| **Neo4j Graph DB** | `7474` / `7687` | The compose service and its `neo4j_data` volume stay declared, but the `graph_neo4j` destination was removed on 2026-09-20, so no destination reads or writes Neo4j. `scripts/purge_neo4j_legacy.py` deletes the previously written `Chunk`/`Document`/`Entity` nodes. |
| **PostgreSQL DB** | `5432` | Three databases: `ingestion` (ingestion API metadata, user/password `ingestion`), `rag` (retrieval: chat, evaluation and guardrails tables in `libs/database/src/rag_db/models/`), and `crawler` (web-scrapper job history). All three share the role `crawler:crawler`, which must exist for `rag` and `crawler`. Each Knowledge Product gets its own pgvector schema `kp_<slug>_<id8>` with a `chunks` table (`universal_fanout.py`). The writer creates an HNSW index with `USING hnsw (embedding vector_cosine_ops)`. pgvector caps an HNSW index at 2000 dimensions. Above that limit the writer skips the index with a warning, and a search falls back to an exact scan. The embedding model in use returns 2048 dimensions, so this is the normal path here. The local ingestion `.env` overrides the API database with SQLite (`sqlite+aiosqlite:///storage/ingestion.db`) |
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

**Retrieval Chat Manager — prerequisites.** `backend/.env` holds Docker service hostnames (`postgres`, `redis`, `qdrant`), which do not resolve from the host. Pass host overrides as process environment; a real environment variable wins over the `.env` file in pydantic-settings. Choose the Qdrant that holds the data you want to read: `6333` for scraper-written `scrape_embeddings`, `6335` for ingestion fanout collections.

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
OTEL_TRACING_ENABLED=false \
  uv run uvicorn rag_api.main:app --host 0.0.0.0 --port 8001
```

`scripts/run-api.sh` runs the same module but reads `backend/.env`, so it only works inside the compose network. `OTEL_TRACING_ENABLED=false` avoids export errors when no collector is reachable on `4318`.

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

**Web-Scrapper API** (port `8000`; the Tracking page and `scrape_embeddings` depend on it). It needs a `crawler` database, which `crawler-db-migrate` creates the tables for:

```bash
cd rag-ingestion-manager
docker compose up -d --no-recreate scraper-migrate scraper-api
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
- Ingestion unit tests: `rag-ingestion-manager/backend/tests/test_page_yielder.py`, `test_fanout_payload.py`, `test_knowledge_destination_schemas.py`, `test_knowledge_product_files.py`
- Retrieval unit tests: `rag-retrieval-chat-manager/backend/tests/unit/` (16 modules, run with `uv run pytest tests/unit -v`); integration test `tests/integration/test_qdrant_retrieve.py` (requires a reachable Qdrant)

---

## 5. Shared Library & Cross-Service Contracts

`shared-libs/platform-common/` (`platform_common`) is the shared integration layer used by ingestion, retrieval and the web-scrapper:

| Module | Role |
|---|---|
| `platform_common/auth.py` | API key verification via `X-API-Key` header **or** `api_key` query parameter (`:12`, `:32`); no-op when the configured key is empty, `/health`, `/docs`, `/openapi.json` and `/redoc` bypass auth (`:11`). Both backends build their dependency with `make_verify_api_key` (`src/shared/auth.py:8`, `rag_shared/auth.py:8`) |
| `platform_common/vector/qdrant_store.py` | Qdrant collection management. The retrieval wrapper accepts a per-call `url`, which is how a knowledge product collection on 6335 is reached while `qdrant_url` keeps pointing at the scraper's 6333. `ensure_collection()` accepts optional `hnsw_m` and `hnsw_ef_construct` tuning. It raises when the stored vector size disagrees with the derived dimension, because recreation deletes every point (`:82-90`) |
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

Ingestion fanout payloads are built by `_build_fanout_payload()` (`universal_fanout.py`) with the `knowledge_product_id` key, so retrieval and visualizers stay aligned. The payload also carries `modality` (`text` or `image`) and `image_ref`, and it keeps `type` at `"text"` for a caption.

**Retrieval Knowledge Store path.** The retrieval backend only *proxies* knowledge products over HTTP to the ingestion manager: `apps/rag-api/src/rag_api/routes/knowledge.py` mounts `APIRouter(prefix="/api/knowledge-products")` and every route forwards to `settings.ingestion_service_url or "http://localhost:8007"`, returning `503` when the ingestion service is unreachable. The proxies are list/create/get/update/delete (update is `PATCH`) and `POST /{id}/test-connection`; the manual sync proxy is gone. There is no ingestion database access from the retrieval side. The retrieval frontend's Knowledge Store page calls the ingestion API directly, since its API client resolves `VITE_API_URL` (default `http://localhost:8007`, `frontend/src/api.ts:3`) through `apiFetch` (`frontend/src/api.ts:375-429`).

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
| **Assistant pipelines (2026-09-21)** | A pipeline can now be a **chat assistant**. The `Pipelines` page creates one from seven fields: an internal name, a description, one **Knowledge Product**, a **RAG Strategy** that the product's enabled destinations can serve, one **Chat Model**, and an optional **Prompt Template** and **Guardrails Config**. The record gained `slug`, `chat_model`, `prompt_template_id` and `guardrails_config_id`, and `qdrant_collection` became nullable, because an assistant owns no documents and reads the product's stores. Migration `011_assistant_pipeline` makes the change and extends the `rag_strategy` enum with `vector`, `lexical`, `relational`; `hybrid` now also means Qdrant dense fused with OpenSearch BM25. The new route `GET /api/pipelines/by-slug/{slug}` is declared before `/{pipeline_id}`, and `_pipeline_to_dict` now returns the nested `knowledge_product` with its destinations, so one call answers both "how do I reach this assistant" and "what does it read". See `vijay-docs/rag-retrieval-chat-manager-docs/02_rag_pipelines_page.md` |
| **Assistant endpoints (2026-09-21)** | Four routes on the retrieval API, addressed by slug rather than UUID: `GET /api/assistants/{slug}`, `POST /api/assistants/{slug}/chat`, `POST /api/assistants/{slug}/chat/stream`, and `POST /v1/assistants/{slug}/chat/completions`. The OpenAI-compatible route lets an OpenAI SDK client point `base_url` at `http://localhost:8001/v1/assistants/{slug}` with no adapter code. The chat routes delegate to the existing `/chat` and `/chat/stream` handlers, so guardrails, retrieval, rerank, generation, persistence and metrics are reused. New readers: OpenSearch BM25 (`vector_core/lexical.py`), pgvector (`vector_core/relational.py`) and reciprocal rank fusion at `k = 60` on `(source_id, file_key, page_index, chunk_index)`. See `vijay-docs/rag-retrieval-chat-manager-docs/14_assistant_pipelines_and_endpoints.md` |
| **Prompt templates (2026-09-21)** | New table `prompt_templates` (retrieval Alembic revision `003`), with CRUD on `/prompt-templates` and a duplicate name answered by `409 PROMPT_TEMPLATE_NAME_TAKEN`. The migration seeds one `Default RAG` row holding the text of `RAG_SYSTEM_PROMPT`. A template is now the assistant's **system message**: `build_rag_prompt()` takes an optional `system_prompt` and falls back to `RAG_SYSTEM_PROMPT`. The retrieved passages and the question keep their user-message shape, so there are no `{context}` or `{question}` placeholders. This replaces the old Prompts page, which wrote catalog overrides to a temporary directory that nothing read. See `vijay-docs/rag-retrieval-chat-manager-docs/04_prompts_management_page.md` |
| **Chat and streaming repairs (2026-09-21)** | `POST /chat/stream` answered `500` on every request: it imported `rag_core.query_router`, a module that never existed, and called `RAGPipeline.stream_chat_self_corrective`, which was never written. Both are gone. `StreamEvent`, `RAGPipeline.stream_chat()` and `Generator.generate_stream()` now exist and stream real token deltas. Guardrails never blocked a turn, because the config stores `ban_list` while the guardrails service names its guard `ban-list`; every check returned 404 and the client read a non-200 as "passed". The client now maps the underscore to a hyphen. `Settings.embedding_model` defaulted to `nvidia-embed-passage`, which the proxy does not serve; it is now `nvidia-embed-textonly`. The `Router`, `Classifier`, `RAG Mode` and `Max Loops` controls left the Chat page, because the query router and self-corrective RAG are not implemented |
| **Retrieval runtime (2026-09-20)** | The retrieval stack now runs on the host end to end. Five defects blocked it, all fixed: `libs/vector-core/pyproject.toml` resolved `platform-common` three levels up instead of four, so `uv sync` failed outside Docker; `rag_db.migrate` used `parents[1]` (`libs/database/src`, no `alembic.ini`) so migrations could not run on the host; four `DELETE` routes annotated `-> Response` without importing it, which made `/openapi.json` return 500 with a Pydantic `class-not-fully-defined` error; `routes/prompts.py` called `has_override`/`write_override`/`clear_override` with a filename alone instead of `(package, name)`, so `GET /prompts` returned 500; and `get_engine()` built a new engine per request, leaking a pool until Postgres refused connections — that one surfaced in the browser as a CORS error, because a 500 from Starlette's error middleware carries no CORS headers. `get_engine()` is now `@lru_cache`d per URL. Pre-existing: 20 of 52 retrieval unit tests fail (`test_dataset_upload.py` expects a 20-item golden dataset, the committed file has 5; `test_stats.py` fails only in a full-suite run). See `vijay-docs/rag-retrieval-chat-manager-docs/overall-rag-retrieval-chat-manager.md` |
| **Guardrails tables (2026-09-20)** | New Alembic revision `002_guardrails_tables` creates the six `guardrails_*` tables. `001_initial_schema` predates the guardrails models and `alembic/env.py` imported only `chat` and `evaluation`, so the tables never existed and all three Guardrails pages failed with "relation does not exist". The revision builds them from `Base.metadata`, so the columns cannot drift from the models |
| **Retrieval Knowledge Store (2026-09-20)** | The retrieval manager's Knowledge Store is now a **view-only mirror** of the ingestion manager's Knowledge Products. Create, edit, delete and every pause or configure control are gone; the page lists products with a derived **RUNNING / PAUSED** badge per product and per destination, a `View` button and a `Refresh`. New read-only detail route `/knowledge-store/:id` with the live fanout timeline (SSE), the ingested-file ledger, the 5 s poll and the destination store inspector. `Refresh` is the manual sync: the ingestion API has no sync route by design, so the page sends `PATCH {}`, which re-registers the product poller and fires one immediate sync. The page re-reads on every route entry (`AppLayout` keeps pages mounted, so the page watches `location.pathname` rather than mounting). The timeline, visualizers and SSE hook were ported byte-identical from the ingestion manager; `api.ts` gained the read-only bindings and lost the three orphaned write functions. See `vijay-docs/rag-retrieval-chat-manager-docs/11_knowledge_store_page.md` |
| **Destination config** | New `backend/apps/api/routes/knowledge_destination_schemas.py` supplies typed field schemas, Docker-aware defaults, `build_destination_types()`, `merge_destination_config()` and `normalize_destination_payload()`; surfaced by `GET /api/knowledge-products/destinations/options` and consumed by the new `frontend/src/components/DestinationConfigFields.tsx` |
| **LiteLLM models** | New `GET /api/knowledge-products/config/litellm-models?model_kind=all\|embedding\|chat\|sparse`: reads `/v1/models` from the LiteLLM proxy and falls back to `settings.unique_embedding_models` / `SUMMARY_MODEL`+`CAPTION_MODEL` / `Qdrant/bm25` when the proxy is unreachable, and reports `default_embedding_model` and `default_caption_model` so the editor defaults to the models this deployment serves |
| **Fanout** | Per-file parallel destination writes with `asyncio.gather(..., return_exceptions=True)`, per-destination error isolation, ETag/size change detection, per-product store names, and purge helpers for Qdrant, OpenSearch, PostgreSQL and RedisVL |
| **Parsing & chunking** | `page_yielder.py` streams PDF (PyMuPDF), DOCX, CSV, JSON, Markdown and text pages; chunking is word-based with defaults `chunk_size=1000` / `chunk_overlap=120` |
| **Qdrant** | The dimension comes from the embedding model output, not from a `vector_size` setting. The collection name is per product (`kp_<slug>_<id8>`). `qdrant_store.py` raises when a stored vector size disagrees with the derived dimension, because recreation deletes every point. `ensure_collection()` also accepts optional `hnsw_m` and `hnsw_ef_construct` tuning |
| **Auth** | `make_verify_api_key` accepts `X-API-Key` or the `api_key` query parameter for browser fetches that cannot set headers |
| **Frontend** | Ingestion nav exposes Overview / Folders / Sources / Knowledge Store, with pages mounted persistently in `AppLayout.tsx` (the Upload item was removed 2026-09-20). Retrieval nav exposes 11 items (Overview, Knowledge Store, Pipelines, Chat, Prompts, Real Time Monitoring, Offline Evaluation, Tracking, Guard Config, Guard Traces, Guard Evaluation); the retrieval Knowledge Store adds a 12th route, the read-only detail page `/knowledge-store/:id`, resolved from `useRouteParams` in `AppLayout.tsx` alongside `source-detail` |
| **Docker** | The ingestion `docker-compose.yaml` and both Dockerfiles build from the monorepo root (`rag-ingestion-manager/docker-compose.yaml:5-6`, `backend/Dockerfile:6-16`, `rag-retrieval-chat-manager/backend/Dockerfile:13-17`). The retrieval `backend/docker-compose.yaml:5,16,37` still references `rag-app-workspace/Dockerfile`, a path that no longer exists in the tree — the usable file is `rag-retrieval-chat-manager/backend/Dockerfile`, and because of that stale reference the retrieval stack runs natively (see §4). The guardrails service and the web-scrapper are declared in the ingestion compose file and start from there |
| **Settings** | Centralized OpenSearch URL in `settings.py`; the legacy `neo4j_*` settings stay declared but no destination reads them; retrieval defaults (port, models, limits) live in `rag_shared/config.py` |
| **Verification** | E2E scripts, all green on 2026-09-21: `scripts/e2e_knowledge_fanout.py` (21 checks), `scripts/e2e_knowledge_pause.py` (14 checks), `scripts/e2e_ingestion_profiles.py` (50 checks) and `scripts/e2e_ingestion_modality.py` (29 checks) and `scripts/e2e_chunk_strategies.py` (19 checks); ingestion unit tests for the page yielder, figure extraction, the fanout payload, the destination schemas, the product files ledger, the connector config validation, profile chunking, the chunk strategies and the modality resolvers (`uv run pytest tests -q`, 59 passing); retrieval unit suite under `tests/unit/` (52 tests, 32 passing — the 20 failures pre-date 2026-09-20) plus the Qdrant integration test. Frontend: all 4 ingestion pages and all 12 retrieval routes were loaded in a browser with a cleared cache and no cookies, collecting console errors, page errors, failed requests and 4xx/5xx responses |

All systems, API routes, models, and interactive visualizers are documented across `vijay-docs/`.
