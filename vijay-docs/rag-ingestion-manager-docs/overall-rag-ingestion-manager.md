# Overall Architecture — RAG Ingestion Manager

**Last updated:** 2026-09-20

## 1. System Overview
`rag-ingestion-manager` is the document ingestion, storage-management, parsing, and multi-sink synchronization service of the `new-multi-rag` platform. It brings unstructured documents from configured sources (per-source MinIO buckets, manual browser uploads, legacy local filesystem folders, Apache NiFi connectors for Google Drive / Amazon S3 / Azure Blob Storage) into MinIO object storage, then executes a per-profile fanout into five RAG storage destinations:

| `destination_type` | Engine | Role | Accepted aliases |
|---|---|---|---|
| `vector_qdrant` | Qdrant | Dense vector similarity in a per-profile collection | — |
| `lexical_opensearch` | OpenSearch | BM25 lexical index | `elasticsearch` |
| `graph_neo4j` | Neo4j | `Document`/`Chunk` graph, optional LiteLLM entity extraction | — |
| `relational_pgvector` | PostgreSQL | Relational chunk table, optional pgvector column | `database_pgvector` |
| `cache_redisvl` | Redis / RedisVL | Semantic cache and parent-child key store | `cache_redis` |

Runtime processes:
- **API** — FastAPI app `backend/apps/api/main.py` bound to container port 8000, published as host port 8007.
- **Worker** — `backend/apps/worker/main.py`: Redis queue consumers plus an APScheduler cron.
- **Pathway worker** — `backend/apps/pathway_worker/main.py`: connector sync queue consumer plus a 10-second scheduled-source poll.
- **Frontend** — Vite/React SPA in `frontend/` (separate from the backend services), host port 5173.

---

## 2. Full Architecture Topology

```
+---------------------------------------------------------------------------------------+
|                                DATA INGESTION PERIMETER                               |
|  [ MinIO buckets ] [ Browser/API uploads ] [ Local FS folders ] [ Google Drive ]      |
|  [ S3 / Azure / GCS / SFTP / Confluence / ... connectors ] [ Web scraper API ]        |
+-------------------------------------------+-------------------------------------------+
                                            |
                                            v
+---------------------------------------------------------------------------------------+
|                          RAG INGESTION MANAGER BACKEND (FastAPI :8007)                |
|  +------------------------------+  +------------------------------+  +--------------+  |
|  | REST routers                 |  | Background processes         |  | Parsing core |  |
|  | /api/uploads                 |  | apps/worker (3 queues +      |  | page_yielder |  |
|  | /api/directories             |  |   APScheduler cron)          |  | PyMuPDF/docx |  |
|  | /api/files                   |  | apps/pathway_worker          |  | csv/json/txt |  |
|  | /api/pipelines               |  |   (pathway_sync_queue +      |  | chunk_text   |  |
|  | /api/sources                 |  |   10s source poll)           |  | SHA-256 hash |  |
|  | /api/knowledge-profiles      |  | in-process source pollers    |  | embeddings   |  |
|  | /health                      |  |   (pathway_sync)             |  | (LiteLLM)    |  |
|  +------------------------------+  +------------------------------+  +--------------+  |
+-------------------------------------------+-------------------------------------------+
                                            |
                                            v
+---------------------------------------------------------------------------------------+
|                     UNIVERSAL MULTI-SINK FANOUT (universal_fanout.py)                 |
|  asyncio.gather over enabled destinations, each dispatched via asyncio.to_thread      |
|  (synchronous per-destination clients), return_exceptions=True                        |
|  DELETE profile -> purge_knowledge_profile() deletes per-file_key artifacts            |
|                                                                                       |
|  +-----------------+ +-----------------+ +-----------------+ +--------------------+    |
|  | vector_qdrant   | | lexical_        | | graph_neo4j     | | relational_        |    |
|  | dense vectors,  | |   opensearch    | | Document/Chunk  | |   pgvector         |    |
|  | HNSW collection | | BM25 index      | | graph nodes     | | chunk table        |    |
|  +-----------------+ +-----------------+ +-----------------+ +--------------------+    |
|                            +---------------------+                                    |
|                            | cache_redisvl       |                                    |
|                            | semantic cache /    |                                    |
|                            | parent-child keys   |                                    |
|                            +---------------------+                                    |
+-------------------------------------------+-------------------------------------------+
                                            |
                                            v
+---------------------------------------------------------------------------------------+
|                       RAG INGESTION MANAGER FRONTEND (Vite :5173)                    |
|  Sidebar NAV: Overview / | Folders /browse | Sources /sources |                      |
|               Knowledge Store /knowledge-store                                        |
|  Pages mounted by AppLayout: HomePage, BrowsePage, DirectoryPage, FileViewerPage,     |
|  SourcesPage, SourceDetailPage, KnowledgeStorePage                                    |
+---------------------------------------------------------------------------------------+
```

---

## 3. Directory & Codebase Structure

```
rag-ingestion-manager/
├── docker-compose.yaml                 # api, worker, pathway-worker, migrate, minio, web, ...
├── backend/
│   ├── Dockerfile
│   ├── alembic.ini
│   ├── alembic/
│   │   └── versions/                   # 001_initial_schema … 009_pipeline_knowledge_profile
│   ├── apps/
│   │   ├── api/
│   │   │   ├── main.py                 # FastAPI app + lifespan + CORS + exception handlers
│   │   │   ├── exceptions.py           # app_error_handler (AppError -> JSON)
│   │   │   └── routes/
│   │   │       ├── uploads.py          # chunked browser upload sessions
│   │   │       ├── directories.py      # virtual workspace directories
│   │   │       ├── files.py            # file metadata, view, rename, delete, append
│   │   │       ├── pipelines.py        # pipeline CRUD, runs, sync, RAG chunk query
│   │   │       ├── sources.py          # sources, connectors, source files, sync triggers
│   │   │       ├── knowledge.py        # knowledge profiles, fanout sync, inspect APIs
│   │   │       └── knowledge_destination_schemas.py   # typed destination field schemas
│   │   ├── worker/
│   │   │   ├── main.py                 # 3 Redis queue loops
│   │   │   └── scheduler.py            # APScheduler CronTrigger from SYNC_CRON_* settings
│   │   └── pathway_worker/
│   │       └── main.py                 # pathway_sync_queue consumer + 10s source poll
│   ├── scripts/
│   │   ├── run-api.sh / run-worker.sh / run-migrate.sh / run-pathway-worker.sh
│   │   └── e2e_knowledge_fanout.py     # E2E fanout/purge verification script
│   ├── tests/
│   │   ├── test_page_yielder.py
│   │   ├── test_fanout_payload.py
│   │   └── test_knowledge_destination_schemas.py
│   └── src/
│       ├── file_manager/               # chunked-upload job engine for the metadata store
│       │   ├── core/                   # jobs/operations, chunk stitching, duplicates, errors
│       │   └── utils/paths.py          # storage_root(), ensure_storage_layout(), sanitizers
│       ├── ingestion_service/
│       │   ├── clients/
│       │   │   ├── source_sync.py      # trigger_source_sync, sync_all_enabled_sources
│       │   │   └── scraper.py          # web-scraper API client
│       │   ├── core/
│       │   │   ├── universal_fanout.py # multi-sink fanout + per-file purge engine
│       │   │   ├── page_yielder.py     # iter_file_pages(): PDF/DOCX/CSV/JSON/text pages
│       │   │   ├── sync_runner.py      # pipeline chunk indexing (sync_pipeline, sync_all_pipelines)
│       │   │   ├── pipeline_runner.py  # pipeline run orchestration (files + scraper)
│       │   │   ├── pathway_sync.py     # connector sync orchestration, live & scheduled source pollers
│       │   │   ├── gdrive_sync.py      # Google Drive connector support
│       │   │   ├── airbyte_connector.py# connector config mapper + pre-sync validation
│       │   │   ├── nifi_sync.py        # NiFi sync engine (s3, azure_blob, gdrive, legacy types)
│       │   │   └── indexer.py          # FileIndexer: chunk + embed + upsert to Qdrant
│       │   ├── embeddings/
│       │   │   ├── client.py           # LiteLLM embedding client, FastEmbed fallback (384-d)
│       │   │   └── sparse_client.py    # re-export of platform_common sparse client
│       │   ├── utils/text_splitter.py  # chunk_text() recursive markdown/text splitter
│       │   ├── vector/                 # re-exports of platform_common Qdrant helpers + search
│       │   └── types.py                # FILE_INGEST_SOURCE_TYPE, WEB_SCRAPE_SOURCE_TYPE
│       └── shared/
│           ├── auth.py                 # verify_api_key bound to settings.api_key
│           ├── config/settings.py      # all settings and defaults
│           ├── db/models.py            # SQLAlchemy models (13 tables)
│           ├── db/session.py           # engine, AsyncSessionLocal, get_db, init_db, close_db
│           ├── queue/client.py         # Redis enqueue/dequeue for all queues
│           └── storage/s3_client.py    # aioboto3/boto3 MinIO client, list/put/get/delete
└── frontend/
    ├── vite.config / index.html / Dockerfile
    └── src/
        ├── api.ts                      # typed client for ingestion, scraper and RAG APIs
        ├── App.tsx                     # legacy /directories* redirects; * -> AppLayout
        ├── components/
        │   ├── AppLayout.tsx           # sidebar NAV + persistent page mounting
        │   ├── PageHeader.tsx, Breadcrumb.tsx, StatusBadge.tsx, Icons.tsx, MarkdownMessage.tsx
        │   ├── DestinationConfigFields.tsx  # renders typed destination fields from the API schema
        │   ├── Sources/                # source/connector form components
        │   └── visualizers/            # DestinationVisualizerModal + 5 sink visualizers
        ├── pages/                      # see §3.1 for mounted vs. present-but-unmounted
        │   ├── HomePage.tsx, BrowsePage.tsx, DirectoryPage.tsx, FileViewerPage.tsx,
        │   ├── SourcesPage.tsx, SourceDetailPage.tsx, KnowledgeStorePage.tsx,
        │   └── PipelinesPage.tsx, TrackingPage.tsx, PromptsPage.tsx, ChatPage.tsx,
        │       EvaluationsPage.tsx, GoldenEvaluationsPage.tsx, GuardrailsConfigPage.tsx,
        │       GuardrailsTracesPage.tsx, GuardrailsEvaluationPage.tsx
        └── utils/format.ts             # formatRelativeTime and friends
```

### 3.1 Frontend routing reality
`AppLayout.tsx` owns navigation and renders pages itself (there are no `<Route>` entries per page). Mounted pages and their paths:

| Path | Page |
|---|---|
| `/` | `HomePage` |
| `/browse` (alias `/directories`) | `BrowsePage` |
| `/browse/:name` (alias `/directories/:name`) | `DirectoryPage` |
| `/browse/:name/view/:fileId`, legacy `/files/:id/view` | `FileViewerPage` |
| `/sources` | `SourcesPage` |
| `/sources/:id` | `SourceDetailPage` |
| `/knowledge-store` | `KnowledgeStorePage` |

Pages are mounted persistently and toggled by visibility, so component state (uploads in progress, open forms) survives navigation. The ingestion app does **not** mount `PipelinesPage`, `TrackingPage`, `PromptsPage`, `ChatPage`, `EvaluationsPage`, `GoldenEvaluationsPage`, `GuardrailsConfigPage`, `GuardrailsTracesPage`, or `GuardrailsEvaluationPage`; those files exist in `frontend/src/pages/` but belong to the retrieval/chat frontend. `App.tsx` only holds legacy redirects (`/directories*`), and `api.ts` additionally exposes scraper (`VITE_SCRAPER_URL`, default `http://localhost:8000`) and retrieval (`VITE_RAG_API_URL`, default `http://localhost:8001`) clients that the mounted ingestion pages do not use.

---

## 4. HTTP API Surface

App factory: `apps/api/main.py`. Routers are included in this order: `uploads`, `directories`, `files`, `pipelines`, `sources`, `knowledge`. Every route depends on `verify_api_key` (routes are registered on the app-level dependency), except the public `/health` path.

| Router prefix | Method | Path | Status | Notes |
|---|---|---|---|---|
| — | `GET` | `/health` | 200 | returns `{"status": "ok"}`; public |
| `/api/uploads` | `POST` | `/init` | 201 | start a chunked upload session (no UI caller since the Upload page was removed) |
| `/api/uploads` | `PUT` | `/{upload_id}/chunks/{chunk_index}` | 204 | upload one chunk (no UI caller) |
| `/api/uploads` | `POST` | `/{upload_id}/complete` | 202 | stitch chunks, validate MIME + verify hash; on a duplicate returns `status: "duplicate"` with no job, otherwise stages the file and enqueues a `file_manager:jobs` job (no UI caller) |
| `/api/directories` | `GET` | `` | 200 | list `{name, id, created_at}` |
| `/api/directories` | `GET` | `/{name}/files` | 200 | non-deleted files in the directory |
| `/api/files` | `GET` | `/{file_id}` | 200 | file detail (incl. duplicate-of name) |
| `/api/files` | `GET` | `/{file_id}/view` | 200 | raw content when status is `synced` |
| `/api/files` | `PATCH` | `/{file_id}` | 202 | rename request -> job |
| `/api/files` | `DELETE` | `/{file_id}` | 202 | delete request -> job |
| `/api/files` | `POST` | `/{file_id}/append/init` | 201 | start append session for a file |
| `/api/files` | `POST` | `/{file_id}/append/{upload_id}/complete` | 202 | finalize append |
| `/api/pipelines` | `GET` | `/options` | 200 | rag strategies, modalities, suggested models, scraper modes |
| `/api/pipelines` | `GET` | `/catalog` | 200 | lightweight list for the chat UI (by description) |
| `/api/pipelines` | `GET` | `/by-description` | 200 | lookup by unique description |
| `/api/pipelines` | `GET` | `` | 200 | list pipelines |
| `/api/pipelines` | `POST` | `` | 201 | create pipeline |
| `/api/pipelines` | `GET` | `/runs` | 200 | all runs, `limit` query (default 100) |
| `/api/pipelines` | `GET` | `/runs/{run_id}` | 200 | single run |
| `/api/pipelines` | `GET` | `/{pipeline_id}` | 200 | pipeline detail |
| `/api/pipelines` | `PATCH` | `/{pipeline_id}` | 200 | directories / scraper settings |
| `/api/pipelines` | `DELETE` | `/{pipeline_id}` | 204 | deletes runs and source links too |
| `/api/pipelines` | `GET` | `/{pipeline_id}/stats` | 200 | `indexed_files_count`, `scraped_pages_count` |
| `/api/pipelines` | `POST` | `/{pipeline_id}/run` | 202 | queue a pipeline run |
| `/api/pipelines` | `GET` | `/{pipeline_id}/runs` | 200 | runs of one pipeline |
| `/api/pipelines` | `POST` | `/{pipeline_id}/sync` | 202 | queue a file sync (`ingestion:sync:jobs`) |
| `/api/pipelines` | `GET` | `/{pipeline_id}/sync-status` | 200 | latest run, or `{"status": "no_runs"}` |
| `/api/pipelines` | `POST` | `/query` | 200 | hybrid/dense/sparse chunk search (`list[RAGChunkItem]`) |
| `/api/sources` | `GET` | `/connectors` | 200 | `{"connectors": [...]}` NiFi connector catalog — exactly `google_drive`, `s3`, `azure_blob` |
| `/api/sources` | `GET` | `` | 200 | list sources (also cleans orphaned local sources) |
| `/api/sources` | `POST` | `` | 201 | create a NiFi connector source or a Manual Upload source |
| `/api/sources` | `GET` | `/{source_id}` | 200 | source detail |
| `/api/sources` | `PATCH` | `/{source_id}` | 200 | update config / monitor modes / intervals (`sync_interval_seconds` or `sync_interval_minutes`) / enabled |
| `/api/sources` | `DELETE` | `/{source_id}` | 200 | delete source, empty and remove its MinIO bucket (or local folder), drop pipeline + knowledge-profile links |
| `/api/sources` | `POST` | `/{source_id}/connectors` | 201 | add connector |
| `/api/sources` | `GET` | `/{source_id}/connectors/{connector_id}` | 200 | connector detail |
| `/api/sources` | `PATCH` | `/{source_id}/connectors/{connector_id}` | 200 | update connector |
| `/api/sources` | `DELETE` | `/{source_id}/connectors/{connector_id}` | 200 | remove connector |
| `/api/sources` | `POST` | `/{source_id}/connectors/{connector_id}/sync` | 200 | enqueue `pathway_sync_queue` for one connector |
| `/api/sources` | `POST` | `/{source_id}/pipeline/{pipeline_id}` | 200 | link source to pipeline (+ optional monitor config) |
| `/api/sources` | `DELETE` | `/{source_id}/pipeline/{pipeline_id}` | 200 | unlink |
| `/api/sources` | `GET` | `/{source_id}/files` | 200 | list files in MinIO bucket or local folder (`prefix` query) |
| `/api/sources` | `POST` | `/{source_id}/files` | 201 | multipart upload (`file`/`files`) |
| `/api/sources` | `DELETE` | `/{source_id}/files` | 200 | delete by `key` query param |
| `/api/sources` | `GET` | `/{source_id}/files/content` | 200 | file bytes with guessed media type |
| `/api/sources` | `POST` | `/{source_id}/sync` | 200 | trigger sync for all connectors |
| `/api/sources` | `POST` | `/{source_id}/events` | 200 | MinIO event webhook receiver |
| `/api/knowledge-profiles` | `GET` | `/destinations/options` | 200 | destination types with typed field schemas and defaults |
| `/api/knowledge-profiles` | `GET` | `/config/litellm-models` | 200 | LiteLLM `/v1/models` listing, `model_kind` in `all\|embedding\|chat\|sparse`, env fallback |
| `/api/knowledge-profiles` | `GET` | `` | 200 | list profiles with sources and destinations |
| `/api/knowledge-profiles` | `POST` | `` | 200 | create profile (400 on duplicate name) |
| `/api/knowledge-profiles` | `GET` | `/{profile_id}` | 200 | profile detail |
| `/api/knowledge-profiles` | `PUT` | `/{profile_id}` | 200 | update profile |
| `/api/knowledge-profiles` | `DELETE` | `/{profile_id}` | 200 | purge artifacts then delete profile |
| `/api/knowledge-profiles` | `POST` | `/{profile_id}/test-connection` | 200 | connectivity test for one destination |
| `/api/knowledge-profiles` | `POST` | `/{profile_id}/sync` | 200 | start fanout in a FastAPI `BackgroundTasks` task |
| `/api/knowledge-profiles` | `GET` | `/{profile_id}/inspect/{destination_type}` | 200 | live store read-back (implemented for `vector_qdrant`, `lexical_opensearch`, `graph_neo4j`; other types return `Visualizer not implemented for this type`) |

Error handling: `AppError` subclasses (NotFound/Validation/Conflict) are mapped by `apps/api/exceptions.py`; any other exception is caught by the global handler and returned as `500 {"error": {"message": ...}}`. CORS is wide open: `allow_origins=["*"]`, `allow_credentials=False`, `allow_methods=["*"]`, `allow_headers=["*"]`.

Lifespan: `ensure_storage_layout()` -> `init_db()` -> `asyncio.create_task(init_all_source_pollers())` on startup; `close_redis()` then `close_db()` on shutdown.

---

## 5. Background Workers & Scheduling

### 5.1 `apps/worker/main.py`
Runs `create_scheduler()` (APScheduler `AsyncIOScheduler`, started but not blocking) and then a polling loop that drains three Redis lists, each with a 2-second timeout; when nothing was handled it sleeps 0.1 s.

| Queue (Redis list) | Setting | Payload | Handler |
|---|---|---|---|
| `file_manager:jobs` | `file_manager_queue` | `{"job_id": ...}` | `file_manager.core.operations.run_job` (upload/append/rename/delete jobs) |
| `ingestion:pipeline:jobs` | `pipeline_queue` | `{"run_id": ...}` | `pipeline_runner.run_pipeline_job` |
| `ingestion:sync:jobs` | `sync_queue` | `{"pipeline_id": ...}` | `sync_runner.sync_pipeline` |

### 5.2 `apps/worker/scheduler.py`
One `CronTrigger` built from the eight `sync_cron_*` settings drives two jobs:

| Job id | Function | Purpose |
|---|---|---|
| `pipeline_file_sync` | `sync_runner.sync_all_pipelines` | re-sync and re-index files for all pipelines with directories |
| `source_connector_sync` | `clients.source_sync.sync_all_enabled_sources` | enqueue `pathway_sync_queue` for enabled sources that are not currently syncing |

Default schedule is every 4 hours at minute 0 second 0 (`sync_cron_hour="*/4"`), configurable down to the year field via `SYNC_CRON_*` env vars.

### 5.3 `apps/pathway_worker/main.py`
- Drains the literal Redis list `pathway_sync_queue` (enqueued by `enqueue_pathway_sync`) and calls `pathway_sync.sync_source_from_pathway(db, source_id)`.
- Every 10 seconds, queries `Source.enabled == True` and calls `sync_source_from_pathway` for each source whose `status != "syncing"`.

### 5.4 In-process source pollers (API)
`init_all_source_pollers()` runs at API startup, selects every `Source.enabled == True`, and calls `register_source_poller(source_id)` for each; the same function is re-invoked whenever a connector is added, updated, or deleted. `register_source_poller` behaviour:
- Mode is **live** when the source-level `connector_monitor_mode` is `live` **or** any of its connectors is `live`; it then starts a loop that calls `sync_source_from_pathway` every 3 seconds.
- Otherwise a **scheduled** loop is started. The interval is taken in seconds first (`connector_sync_interval_seconds`, else the first connector's `sync_interval_seconds`), and only then falls back to minutes (`connector_sync_interval_minutes`, else the first connector's `sync_interval_minutes`, defaulting to 5 minutes). The result is floored at 5 seconds.
- Registration also fires one immediate `_trigger_initial_sync` so a newly enabled source does not wait for the first sleep. Any existing poller for that source is cancelled first, and pollers are only started for enabled sources.
- A source whose `connector_type` is one of the markers `minio`, `minio_manual`, `manual_upload`, `local_filesystem` and which has no `SourceConnector` rows is skipped (`pathway_sync_no_connectors`) instead of synthesising a fake connector.

Separately, `pathway_sync.start_minio_monitor` / `start_local_fs_monitor` provide per-bucket watchers and are started from source-management paths (for example when a source is linked to a pipeline).

---

## 6. Storage Layout

`storage_path` defaults to `./storage`; `ensure_storage_layout()` creates the sub-directories at runtime (deliberately not baked into the Docker image, because `api` and `worker` mount the same named volume).

```
storage/                       # settings.storage_path, mounted as /app/storage (volume file_storage)
├── temp/<upload_id>/          # chunk staging during upload
├── staging/<job_id>/          # assembled file before commit
├── uploads/<directory_name>/  # final files of the metadata store
└── local_sources/<folder_name>/   # created on demand for local_filesystem sources
```

MinIO object storage (`settings.minio_endpoint`, default `minio:9000`):
- Every source owns a deterministic bucket. Connector/upload sources: `_make_bucket_name()` = `f"{minio_bucket_prefix}-{name}-{source_id[:8]}"` with `minio_bucket_prefix` default `source`.
- Local filesystem sources use the pseudo-bucket name `local-<folder_name>` and are backed by `storage/local_sources/<folder_name>`; the `minio_bucket` column still holds that name.
- `s3_client.py` creates its endpoint URL from `minio_endpoint` (prefixing `http://`/`https://` per `minio_use_ssl`) and rewrites `minio:9000` to `127.0.0.1:9000` when `minio` does not resolve (host-run development).

PostgreSQL is the metadata store (`database_url`; async form via the `async_database_url` property, which swaps in `postgresql+asyncpg://`).

---

## 7. Authentication

- `src/shared/auth.py` builds `verify_api_key` with `platform_common.auth.make_verify_api_key(lambda: get_settings().api_key)`.
- The key is accepted in the `X-API-Key` header or the `api_key` query parameter; a mismatch or absence returns `401` with `detail="Invalid or missing API key"`.
- When `api_key` is empty (the default) authentication is a no-op, so a fresh checkout runs unauthenticated.
- Public paths, always reachable even when a key is configured: `/health`, `/docs`, `/openapi.json`, `/redoc`.
- The dependency is attached to the whole app, so every router listed in §4 is protected; `/health` is only reachable because it is a public path.

---

## 8. Configuration Settings (`src/shared/config/settings.py`)

Loaded with pydantic-settings from an optional `.env` (`extra="ignore"`) and cached by `get_settings()` (`lru_cache`).

| Setting | Default | Used for |
|---|---|---|
| `database_url` | `postgresql://ingestion:ingestion@localhost:5432/ingestion` | metadata store |
| `redis_url` | `redis://localhost:6379/0` | job queues and RedisVL destination defaults |
| `storage_path` | `./storage` | local staging / uploads / local sources |
| `file_manager_queue` | `file_manager:jobs` | upload/append/rename/delete jobs |
| `pipeline_queue` | `ingestion:pipeline:jobs` | pipeline run jobs |
| `sync_queue` | `ingestion:sync:jobs` | pipeline file-sync jobs |
| `chunk_size_bytes` | `5242880` (5 MB) | reference chunk size for clients |
| `qdrant_url` | `http://localhost:6333` | vector destination default / search |
| `qdrant_api_key` | `qdrant` | Qdrant default |
| `qdrant_collection` | `scrape_embeddings` | fallback collection for chunk search when the request omits one (pipelines store their own `qdrant_collection`) |
| `litellm_base_url` | `http://host.docker.internal:4000` | embeddings, entity extraction, model listing |
| `openai_api_key` | `sk-bot` | LiteLLM bearer token |
| `embedding_model` | `nvidia-embed-passage` | default dense model |
| `multimodal_embedding_model` | `nvidia-embed-passage` | image modality |
| `sparse_embedding_model` | `Qdrant/bm25` | sparse/lexical model |
| `embed_workers` | `4` | embedding concurrency hint |
| `sync_cron_year/month/day/week/dow` | `*` | APScheduler cron fields |
| `sync_cron_hour` | `*/4` | cron hour field |
| `sync_cron_minute` | `0` | cron minute field |
| `sync_cron_second` | `0` | cron second field |
| `minio_endpoint` | `minio:9000` | object storage |
| `minio_access_key` / `minio_secret_key` | `minioadmin` / `minioadmin` | object storage credentials |
| `minio_use_ssl` | `"false"` | object storage TLS |
| `minio_bucket_prefix` | `source` | generated bucket names |
| `minio_region` | `us-east-1` | object storage region |
| `scraper_api_url` | `http://localhost:8000` | web-scraper API |
| `scraper_api_key` | `""` | web-scraper API key; falls back to `api_key` when unset |
| `api_key` | `""` | API auth; empty disables auth |
| `opensearch_url` | `http://opensearch:9200` | lexical destination fallback |
| `neo4j_bolt_uri` | `bolt://neo4j:7687` | graph destination default |
| `neo4j_http_url` | `http://neo4j:7474` | graph destination default |
| `neo4j_user` / `neo4j_password` | `neo4j` / `password` | graph destination credentials |
| `neo4j_auth_disabled` | `True` | when true the Neo4j driver connects with `auth=None` |

Derived values: `embedding_model_options` (`embedding_model`, `multimodal_embedding_model`, `text-embedding-3-small`, `text-embedding-3-large`), `unique_embedding_models` (deduplicated), `async_database_url` (asyncpg URL).

Destination defaults that are not settings live in `apps/api/routes/knowledge_destination_schemas.py`, e.g. `vector_qdrant.vector_size = 2048`, `collection_name = knowledge_qdrant_collection`, `lexical_opensearch.index_name = knowledge_lexical_index`, `bm25_k1 = 1.2`, `bm25_b = 0.75`, `hnsw_m = 16`, `hnsw_ef_construct = 100`. `merge_destination_config()` merges user input over these defaults and `normalize_destination_payload()` drops unknown destination ids — it does not add implicit destinations.

---

## 9. Database Schema & Migrations

`src/shared/db/models.py` defines 13 tables:

| Table | Model | Purpose |
|---|---|---|
| `directories` | `Directory` | virtual workspace folders |
| `files` | `FileRecord` | file metadata, hash, status (`processing/synced/failed/deleted/duplicate`) |
| `sync_jobs` | `SyncJob` | upload/append/rename/delete jobs on the metadata store |
| `chunk_uploads` | `ChunkUpload` | resumable chunked upload sessions |
| `sources` | `Source` | external source + its dedicated MinIO bucket, monitor modes, metrics |
| `source_connectors` | `SourceConnector` | per-connector type/config/monitor mode |
| `pipeline_sources` | `PipelineSource` | M2M pipeline<->source link with per-link monitor config |
| `pipelines` | `Pipeline` | rag strategy, embedding config, chunking, scraper settings, `knowledge_profile_id` |
| `pipeline_runs` | `PipelineRun` | run status, counters, scraper job ids |
| `indexed_files` | `IndexedFile` | per-pipeline indexing state keyed by `content_hash` (`file_id` or `source_id` + `file_key`) |
| `knowledge_profiles` | `KnowledgeProfile` | name, enabled, status, `error_message`, `last_sync_at` |
| `knowledge_profile_sources` | `KnowledgeProfileSource` | M2M profile<->source (MinIO bucket) |
| `knowledge_destination_configs` | `KnowledgeDestinationConfig` | per-destination `enabled`, `config` (JSONB), `status`, `error_message`, `last_sync_at` |

Migrations in `backend/alembic/versions/` (linear chain, `001` has no parent):

| Revision | File | Change |
|---|---|---|
| `001_initial` | `001_initial_schema.py` | directories, files, sync_jobs, chunk_uploads |
| `002_pipelines` | `002_pipelines.py` | pipelines, pipeline_runs (+ `rag_strategy`, `index_modality` enum types) |
| `003_pipeline_description` | `003_pipeline_description.py` | unique pipeline description + per-pipeline embedding/collection config |
| `004_indexed_files` | `004_indexed_files.py` | indexed_files table with `(pipeline_id, content_hash)` and `(pipeline_id, file_id)` indexes |
| `005_sources` | `005_sources.py` | sources, pipeline_sources |
| `006_source_indexed_files` | `006_source_indexed_files.py` | allow indexed_files to reference source-backed files (`source_id`, `file_key`) |
| `007_multi_connector_sources` | `007_multi_connector_sources.py` | source_connectors, connector/pipeline monitor modes, per-link PipelineSource config |
| `008_knowledge_store` | `008_knowledge_store.py` | knowledge_profiles, knowledge_profile_sources, knowledge_destination_configs |
| `009_pipeline_knowledge_profile` | `009_pipeline_knowledge_profile.py` | `pipelines.knowledge_profile_id` |

`models.py` also installs SQLite compilers for `JSONB`/`UUID` so the schema can be created on SQLite (used by tests).

---

## 10. Ingestion & Fanout Pipeline (as implemented)

### 10.1 Metadata-store path (directories, pipelines, Qdrant)
1. Files enter a directory via `POST /api/uploads/init` -> `PUT .../chunks/{n}` -> `POST .../complete`, which enqueues a `file_manager:jobs` job; the worker moves the staged file into `storage/uploads/<directory>/<uuid-name>`, sets `stored_name`/`relative_path`, size, `content_hash` (from the job payload when present) and `status = synced`.
2. `POST /api/pipelines/{id}/sync` (or the cron job `sync_all_pipelines`) enqueues `ingestion:sync:jobs`; `sync_runner.sync_pipeline` builds the sets of new / changed / deleted files from a `PipelineRun`, the pipeline's `directory_names`, its linked source buckets, and the existing `indexed_files` rows (compared by `content_hash` and by `file_id` or `(source_id, file_key)`), then calls `FileIndexer` on the new and changed files and drops the deleted ones from the collection.
3. `indexer.py` splits page text with `chunk_text(chunk_size, chunk_overlap)`, embeds dense vectors through `EmbeddingClient` (LiteLLM `/v1/embeddings`, FastEmbed `BAAI/bge-small-en-v1.5` fallback) and sparse vectors when the strategy is `sparse`/`hybrid` (also for `multimodal`/`metadata` with text modality), then upserts points into the pipeline's Qdrant collection. Payloads carry `source_type="file_ingest"`, `source_id`, `source_locator`, `pipeline_id`, `file_id`, `directory_name`, `chunk_index`, `page_index`, `content`, `rag_strategy`, `embedding_model`.
4. `POST /api/pipelines/query` performs dense/sparse/hybrid search through `platform_common` Qdrant helpers.

### 10.2 Source path (connectors, fanout to the 5 sinks)
1. `POST /api/sources` creates a `Source` row with a deterministic MinIO bucket. A **NiFi connector source** (`source_type: "minio"`) starts with no connectors and gets them through `POST /api/sources/{id}/connectors`, where the type must be one of the three catalogue ids `google_drive`, `s3`, `azure_blob`. A **Manual Upload source** (`source_type: "minio_manual"`) writes files straight into its bucket through `POST /api/sources/{id}/files`. Legacy local filesystem rows still resolve to `local-<folder>`.
2. Manual sync (`POST /api/sources/{id}/sync`, `.../connectors/{cid}/sync`, file upload/delete, MinIO event webhook, or the cron/10-second poll) marks the source `syncing` and pushes `pathway_sync_queue`.
3. `pathway_worker` calls `pathway_sync.sync_source_from_pathway`, which runs the connector/dir sync into the source's MinIO bucket and then triggers the linked pipelines' fanout.
4. A Knowledge Profile (`knowledge_profiles`) links one or more sources (`knowledge_profile_sources`) and one row per enabled destination (`knowledge_destination_configs`).
5. `POST /api/knowledge-profiles/{id}/sync` sets `status="syncing"`, clears `error_message`, and schedules `_background_fanout_sync`; that helper opens its own session, calls `execute_universal_fanout_sync`, then writes back `profile.status` (the fanout's `status` value, default `"synced"`), `profile.last_sync_at`, and — only if the returned dict contains an `error_message` key — `profile.error_message`. Every enabled destination row is then set to `status="synced"` with the same timestamp.
6. `execute_universal_fanout_sync(db, profile)`:
   - resolves the profile with sources and destinations loaded, keeps only enabled destinations and linked sources; with no linked sources it returns a success result with zero counters;
   - per source, builds the set of live objects — `list_objects(bucket)` for MinIO, `storage/local_sources/<folder>.rglob("*")` for local sources — and loads existing `IndexedFile` rows for `source_id` keyed by `file_key`;
   - computes `hashlib.sha256(bytes).hexdigest()` per object: unchanged hash -> skipped; changed hash -> `purge_file_from_destinations(profile, key)` then re-fanout; absent from the live set but present in `indexed_files` -> purge + delete the tracking row;
   - writes the object to a `tempfile.NamedTemporaryFile`, then `page_yielder.iter_file_pages()` yields `FilePage(page_index, text, image_png)` rows (PyMuPDF for PDF, python-docx, csv, json, plain text/markdown fallback);
   - fans out with `asyncio.gather(*[_fanout_to_destination(...) for dest in enabled_destinations], return_exceptions=True)`, where each `_fanout_to_destination` offloads the synchronous `_sync_fanout_to_destination` via `asyncio.to_thread`;
   - records/refreshes `IndexedFile(source_id, file_key, content_hash, indexed_at)`;
   - returns `{"status", "files_processed", "files_added", "files_updated", "files_deleted", "pages_processed", "destinations_synced"}`.
7. Per-destination writes (all synchronous, REST/driver level, no driver pooling):
   - `vector_qdrant` — embeds each page's text with the destination's `embedding_model` through LiteLLM, then `QdrantVectorStore.ensure_collection(vector_size=<configured or auto-detected>, enable_sparse=False)` and `upsert_batch` with one point per page carrying the fanout payload. The schema exposes `distance`, `hnsw_m`, `hnsw_ef_construct`, `quantization` and `on_disk_payload`, but this branch only applies `vector_size`.
   - `lexical_opensearch` — `PUT {index_name}` with `number_of_shards` / `number_of_replicas` / `refresh_interval` index settings (BM25 k1/b are **not** applied to the mapping), then indexes one document per page containing `file_key`, `page_index`, `content`/`text`, `source_id`, `source_locator`, `created_at`, `sparse_model`, `bm25_k1`, `bm25_b`; optional basic auth.
   - `graph_neo4j` — `Document`/`Chunk` nodes with `CONTAINS_CHUNK` relationships; when `entity_extraction_enabled`, entities are extracted through LiteLLM chat completions (`entity_extraction_model`, default `gpt-4o-mini`, capped by `max_entities_per_chunk`) and attached with `MENTIONS` relationships. Auth is `None` when `auth_disabled` (destination config, default from `neo4j_auth_disabled`).
   - `relational_pgvector` — inserts one row per page into `schema_name.table_name` (default `public.knowledge_chunks`); when `store_embeddings` is enabled (default `True`) the row carries the dense embedding, otherwise text only.
   - `cache_redisvl` — writes one key per chunk with `ttl_seconds` (default `86400`), `parent_child_mapping` (default `True`), `similarity_threshold` stored in the payload, and optional RAPTOR summaries when `raptor_summaries` is enabled.
8. `purge_knowledge_profile()` (used by `DELETE /api/knowledge-profiles/{id}`) walks the profile's linked `source_id`s, purges each tracked `file_key` from all enabled destinations, deletes the `IndexedFile` rows, and returns `{"purged_files", "source_ids", "destinations"}`. The API then deletes the profile row (destinations and source links cascade).

---

## 11. Key Engineering Invariants
1. **Content-hash differential ingestion**: `IndexedFile` rows keyed by `(pipeline_id, content_hash)` and `(pipeline_id, source_id, file_key)` let both the pipeline runner and the fanout engine skip unchanged bytes; changed files are purged in destinations before re-indexing, removed files are purged and their tracking rows deleted. Source file identity is the SHA-256 of the object bytes.
2. **Parallel multi-sink fanout with isolated failures**: destinations are written concurrently (`asyncio.gather(..., return_exceptions=True)` over `asyncio.to_thread` calls), so one failing sink does not abort the others. A raised destination error is logged (`fanout_destination_failed`), its destination is omitted from the returned `destinations_synced` list, and the engine continues. Errors are not persisted per destination: nothing writes `KnowledgeDestinationConfig.error_message`, and `KnowledgeProfile.error_message` is only assigned when the fanout result dict contains an `error_message` key — the current result dict never does, so the profile row keeps the `None` it was set to when the sync started. After the run, every enabled destination row is set to `status="synced"` with `last_sync_at = now()` regardless of individual sink outcomes.
3. **Retrieval-aligned payloads**: fanout documents carry `source_type`, `source_id`, `source_locator`, `file_key`, `file_name`/`original_name`, `page_index`, `chunk_index`, `content`/`text`, `knowledge_profile_id`, and `created_at`; the pipeline indexer emits `source_type="file_ingest"`, `source_locator="<directory>/<file>#page-<n>"`, plus pipeline/strategy/embedding metadata for `platform_common` hit mapping.
4. **Profile delete purge**: `DELETE /api/knowledge-profiles/{id}` purges indexed artifacts from all enabled destinations before deleting the profile, and returns a `purge_summary`.
5. **Live inspectability (partial)**: `GET /api/knowledge-profiles/{id}/inspect/{destination_type}` serves live read-back data for `vector_qdrant` (collection info + scroll of points with a pseudo-3D projection), `lexical_opensearch` (match-all hits + aggregated term frequencies), and `graph_neo4j`; other destination types return `{"message": "Visualizer not implemented for this type"}`.
6. **Single API-key gate**: every route is behind `verify_api_key` (header or query param), disabled only when `api_key` is empty.

---

## 12. Runtime Services & Ports (`docker-compose.yaml`)
Compose file is shared with the retrieval stack; the ingestion-relevant services are:

| Service | Image / build | Command | Ports |
|---|---|---|---|
| `migrate` | backend Dockerfile | `sh /app/scripts/run-migrate.sh` | — |
| `api` | backend Dockerfile | `sh /app/scripts/run-api.sh` | `8007:8000` |
| `worker` | backend Dockerfile | `sh /app/scripts/run-worker.sh` | — |
| `pathway-worker` | backend Dockerfile | `python -m apps.pathway_worker.main` | — |
| `web` | `frontend/Dockerfile` | Vite dev server | `5173:5173` (`VITE_API_URL=http://localhost:8007`) |
| `minio` | `minio/minio:RELEASE.2024-01-16T16-07-38Z` | `server /data --console-address ":9001"` | `9000:9000`, `9001:9001` |
| `nifi` | `apache/nifi:1.24.0` | — | `8443:8443` |
| `scraper-api` / `scraper-worker` / `scraper-migrate` | `tharun0511/web-scrapper-wokspace:latest` | — | `8000:8000` (scraper API) |
| `qdrant` | `qdrant/qdrant:v1.18.0` | — | `6333:6333` |
| `redis` | `redis:7-alpine` | — | `6379:6379` |
| `postgres` | `postgres:16-alpine` | — | `5432:5432` |
| `otel-collector` | `otel/opentelemetry-collector:0.148.0` | — | `4317:4317`, `4318:4318` |
| `rag-migrate` / `rag-api` / `eval-worker` (+ guardrails services) | retrieval Dockerfile on this compose file | — | `8001:8001` (`rag-api`) |

Shared volumes: `file_storage` (`api`, `worker`, `pathway-worker` mount it at `/app/storage`), `hf-cache` (`worker` and the retrieval `rag-api`), `minio_data`, `pg_data`, `qdrant_data`, `nifi_data`, `scraper_data`. All ingestion services set `extra_hosts: host.docker.internal:host-gateway` so `litellm_base_url` can point at a host-run LiteLLM proxy.

---

## 13. Verification
- E2E: `backend/scripts/e2e_knowledge_fanout.py` (delete -> purge verify -> create -> sync -> inspect all sinks).
- Tests: `backend/tests/test_page_yielder.py`, `backend/tests/test_fanout_payload.py`, `backend/tests/test_knowledge_destination_schemas.py`, `backend/tests/test_connector_config_validation.py`.
