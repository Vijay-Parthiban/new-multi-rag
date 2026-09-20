# Overall Architecture — RAG Ingestion Manager

**Last updated:** 2026-09-20

## 1. System Overview
`rag-ingestion-manager` is the document ingestion, storage-management, parsing, and multi-sink synchronization service of the `new-multi-rag` platform. It brings unstructured documents from configured sources (per-source MinIO buckets, manual browser uploads, legacy local filesystem folders, Apache NiFi connectors for Google Drive / Amazon S3 / Azure Blob Storage) into MinIO object storage, then executes a per-product fanout into four RAG storage destinations:

| `destination_type` | Engine | Role | Accepted aliases |
|---|---|---|---|
| `vector_qdrant` | Qdrant | Dense vector similarity in a per-product collection | — |
| `lexical_opensearch` | OpenSearch | BM25 lexical index | `elasticsearch` |
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
|  | /api/sources                 |  |   10s source poll)           |  | ETag + size  |  |
|  | /api/knowledge-products      |  | in-process source pollers    |  | embeddings   |  |
|  | /health                      |  |   (pathway_sync)             |  | (LiteLLM)    |  |
|  +------------------------------+  +------------------------------+  +--------------+  |
+-------------------------------------------+-------------------------------------------+
                                            |
                                            v
+---------------------------------------------------------------------------------------+
|                     UNIVERSAL MULTI-SINK FANOUT (universal_fanout.py)                 |
|  asyncio.gather over enabled destinations, each dispatched via asyncio.to_thread      |
|  (synchronous per-destination clients), return_exceptions=True                        |
|  DELETE product -> purge_knowledge_product() removes per-file_key artifacts            |
|                                                                                       |
|  +-----------------+ +-----------------+ +-----------------+ +--------------------+    |
|  | vector_qdrant   | | lexical_        | | relational_     | | cache_redisvl      |    |
|  | dense vectors,  | |   opensearch    | |   pgvector      | | semantic cache /   |    |
|  | HNSW collection | | BM25 index      | | chunk table     | | parent-child keys  |    |
|  +-----------------+ +-----------------+ +-----------------+ +--------------------+    |
+-------------------------------------------+-------------------------------------------+
                                            |
                                            v
+---------------------------------------------------------------------------------------+
|                       RAG INGESTION MANAGER FRONTEND (Vite :5173)                    |
|  Sidebar NAV: Overview / | Folders /browse | Sources /sources |                      |
|     Ingestion Profiles /ingestion-profiles | Knowledge Store /knowledge-store         |
|  Pages mounted by AppLayout: HomePage, BrowsePage, DirectoryPage, FileViewerPage,     |
|  SourcesPage, SourceDetailPage, IngestionProfilesPage, KnowledgeStorePage,            |
|  KnowledgeProductPage                                                                 |
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
│   │   └── versions/                   # 001_initial_schema … 010_knowledge_products
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
│   │   │       ├── knowledge_products.py  # knowledge products, pause, files, SSE, inspect APIs
│   │   │       ├── ingestion_profiles.py  # reusable destination + chunking profiles, apply-profile
│   │   │       └── knowledge_destination_schemas.py   # typed destination field schemas
│   │   ├── worker/
│   │   │   ├── main.py                 # 3 Redis queue loops
│   │   │   └── scheduler.py            # APScheduler CronTrigger from SYNC_CRON_* settings
│   │   └── pathway_worker/
│   │       └── main.py                 # pathway_sync_queue consumer + 10s source poll
│   ├── scripts/
│   │   ├── run-api.sh / run-worker.sh / run-migrate.sh / run-pathway-worker.sh
│   │   ├── e2e_knowledge_fanout.py     # E2E fanout, store isolation and purge verification script
│   │   ├── e2e_knowledge_pause.py      # E2E pause/resume verification script
│   │   ├── e2e_ingestion_profiles.py   # E2E profiles, chunking and re-apply verification script
│   │   ├── e2e_ingestion_modality.py   # E2E env-only field surface and caption verification script
│   │   ├── e2e_chunk_strategies.py     # E2E chunk strategy record-shape verification script
│   │   └── purge_neo4j_legacy.py       # one-shot legacy graph-node purge
│   ├── tests/
│   │   ├── test_page_yielder.py
│   │   ├── test_page_yielder_figures.py
│   │   ├── test_fanout_payload.py
│   │   ├── test_knowledge_destination_schemas.py
│   │   ├── test_knowledge_product_files.py
│   │   ├── test_ingestion_profile_chunking.py
│   │   └── test_ingestion_modality_resolvers.py
│   └── src/
│       ├── file_manager/               # chunked-upload job engine for the metadata store
│       │   ├── core/                   # jobs/operations, chunk stitching, duplicates, errors
│       │   └── utils/paths.py          # storage_root(), ensure_storage_layout(), sanitizers
│       ├── ingestion_service/
│       │   ├── clients/
│       │   │   ├── source_sync.py      # trigger_source_sync, sync_all_enabled_sources
│       │   │   └── scraper.py          # web-scraper API client
│       │   ├── core/
│       │   │   ├── universal_fanout.py # four-destination fanout, figure captioning + per-file purge
│       │   │   ├── knowledge_sync.py   # product poller: register_knowledge_poller, sync_knowledge_product
│       │   │   ├── knowledge_events.py # SSE event bus for the live fanout timeline
│       │   │   ├── page_yielder.py     # iter_file_pages(): PDF/DOCX/CSV/JSON/text pages + embedded PDF figures
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
│       │   ├── utils/text_splitter.py  # chunk_text() + chunk_parent_child(): the seven chunk strategies
│       │   ├── vector/                 # re-exports of platform_common Qdrant helpers + search
│       │   └── types.py                # FILE_INGEST_SOURCE_TYPE, WEB_SCRAPE_SOURCE_TYPE
│       └── shared/
│           ├── auth.py                 # verify_api_key bound to settings.api_key
│           ├── config/settings.py      # all settings and defaults
│           ├── db/models.py            # SQLAlchemy models (16 tables)
│           ├── db/session.py           # engine, AsyncSessionLocal, get_db, init_db, _ensure_sqlite_renames, close_db
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
        │   └── visualizers/            # DestinationVisualizerModal + 4 destination visualizers
        ├── pages/                      # see §3.1 for mounted vs. present-but-unmounted
        │   ├── HomePage.tsx, BrowsePage.tsx, DirectoryPage.tsx, FileViewerPage.tsx,
        │   ├── SourcesPage.tsx, SourceDetailPage.tsx, IngestionProfilesPage.tsx,
        │   ├── KnowledgeStorePage.tsx, KnowledgeProductPage.tsx,
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
| `/ingestion-profiles` | `IngestionProfilesPage` |
| `/knowledge-store` | `KnowledgeStorePage` |
| `/knowledge-store/:id` | `KnowledgeProductPage` |

Pages are mounted persistently and toggled by visibility, so component state (uploads in progress, open forms) survives navigation. The ingestion app does **not** mount `PipelinesPage`, `TrackingPage`, `PromptsPage`, `ChatPage`, `EvaluationsPage`, `GoldenEvaluationsPage`, `GuardrailsConfigPage`, `GuardrailsTracesPage`, or `GuardrailsEvaluationPage`; those files exist in `frontend/src/pages/` but belong to the retrieval/chat frontend. `App.tsx` only holds legacy redirects (`/directories*`), and `api.ts` additionally exposes scraper (`VITE_SCRAPER_URL`, default `http://localhost:8000`) and retrieval (`VITE_RAG_API_URL`, default `http://localhost:8001`) clients that the mounted ingestion pages do not use.

---

## 4. HTTP API Surface

App factory: `apps/api/main.py`. Routers are included in this order: `uploads`, `directories`, `files`, `pipelines`, `sources`, `knowledge_products`, `ingestion_profiles`. Every route depends on `verify_api_key` (routes are registered on the app-level dependency), except the public `/health` path.

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
| `/api/sources` | `DELETE` | `/{source_id}` | 200 | delete source, empty and remove its MinIO bucket (or local folder), drop pipeline + knowledge-product links |
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
| `/api/knowledge-products` | `GET` | `/destinations/options` | 200 | destination types with the 15 typed field schemas, defaults and `namespace_fields` |
| `/api/knowledge-products` | `GET` | `/config/litellm-models` | 200 | LiteLLM `/v1/models` listing, `model_kind` in `all\|embedding\|chat\|sparse`, `default_embedding_model`, `default_caption_model`, env fallback |
| `/api/knowledge-products` | `GET` | `` | 200 | list products with sources and destinations, newest first |
| `/api/knowledge-products` | `POST` | `` | 201 | create product (400 on duplicate name); an optional `ingestion_profile_id` copies that profile's destinations; registers the poller and starts ingestion |
| `/api/knowledge-products` | `GET` | `/{product_id}/files` | 200 | ingested-file ledger, `?status=&limit=50&offset=0` -> `{"files": [...], "total": n}` |
| `/api/knowledge-products` | `GET` | `/{product_id}/events` | 200 | SSE stream of fanout events (`knowledge_events.py`), `: keepalive` every 15 s |
| `/api/knowledge-products` | `GET` | `/{product_id}` | 200 | product detail |
| `/api/knowledge-products` | `PATCH` | `/{product_id}` | 200 | partial update; deletes destination rows absent from the payload |
| `/api/knowledge-products` | `DELETE` | `/{product_id}` | 200 | purge artifacts then delete product |
| `/api/knowledge-products` | `PATCH` | `/{product_id}/destinations/{destination_id}` | 200 | body `{enabled}`; pause or resume one destination |
| `/api/knowledge-products` | `POST` | `/{product_id}/pause-all` | 200 | pause every destination of the product |
| `/api/knowledge-products` | `POST` | `/{product_id}/resume-all` | 200 | resume every destination of the product |
| `/api/knowledge-products` | `POST` | `/{product_id}/apply-profile` | 200 | re-copy the linked Ingestion Profile, purge the stores it removes or changes, return `{added, updated, removed, purged_files}`; `422 PROFILE_REQUIRED` when the product has no link |
| `/api/knowledge-products` | `POST` | `/{product_id}/test-connection` | 200 | connectivity test for one destination |
| `/api/knowledge-products` | `GET` | `/{product_id}/inspect/{destination_type}` | 200 | live store read-back, implemented for all four destinations |
| `/api/ingestion-profiles` | `GET` | `` | 200 | list Ingestion Profiles with their destinations and `product_count`, newest first |
| `/api/ingestion-profiles` | `POST` | `` | 201 | create an Ingestion Profile; `400` on a duplicate name, `422 CHUNK_OVERLAP_TOO_LARGE` on a bad chunk pair, `422 CAPTION_MODEL_REQUIRED` when `text_images` has no caption model |
| `/api/ingestion-profiles` | `GET` | `/{profile_id}` | 200 | one Ingestion Profile with its destinations and usage count |
| `/api/ingestion-profiles` | `PATCH` | `/{profile_id}` | 200 | partial update; a supplied `destinations` list replaces the whole set |
| `/api/ingestion-profiles` | `DELETE` | `/{profile_id}` | 200 | delete an unreferenced profile; `409 PROFILE_IN_USE` with `product_count` when a product references it |

Error handling: `AppError` subclasses (NotFound/Validation/Conflict) are mapped by `apps/api/exceptions.py`; any other exception is caught by the global handler and returned as `500 {"error": {"message": ...}}`. CORS is wide open: `allow_origins=["*"]`, `allow_credentials=False`, `allow_methods=["*"]`, `allow_headers=["*"]`.

Lifespan: `ensure_storage_layout()` -> `init_db()` -> `asyncio.create_task(init_all_source_pollers())` and `asyncio.create_task(init_all_knowledge_pollers())` on startup; `close_redis()` then `close_db()` on shutdown.

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
- The **enabled connector rows decide the schedule**. Mode is **live** when any enabled connector is `live`; then the loop calls `sync_source_from_pathway` every 3 seconds.
- Otherwise a **scheduled** loop is started with the smallest interval among the enabled connectors: `sync_interval_seconds` first (floored at 5 s), else `sync_interval_minutes × 60`, else 5 minutes.
- A source with no connector rows at all (legacy single-connector sources) falls back to the source-level `connector_monitor_mode` and interval fields.
- When every connector is paused, or the source is a marker-type bucket (`minio`, `minio_manual`, `manual_upload`, `local_filesystem`) with no connector rows, the poller is stopped and `register_source_poller` returns early (`source_poller_skipped`).
- Registration also fires one immediate `_trigger_initial_sync` so a newly configured connector does not wait for the first sleep. Any existing poller for that source is cancelled first, and pollers are only started for enabled sources.
- A source whose `connector_type` is one of the markers above and which has no `SourceConnector` rows never synthesises a fake connector.
- Pausing is `PATCH` with `{"enabled": false}`. The connector row's `enabled` is the pause switch for a single connector; pausing all of them means one such call per connector. `_do_sync_source_from_pathway` filters on it, so a paused connector is skipped by the poller, the manual sync endpoint, the MinIO webhook and the cron sweep alike.

Separately, `pathway_sync.start_minio_monitor` / `start_local_fs_monitor` provide per-bucket watchers and are started from source-management paths (for example when a source is linked to a pipeline).

### 5.5 In-process Knowledge Product pollers (API)
`init_all_knowledge_pollers()` runs at API startup, selects every `KnowledgeProduct.enabled == True`, and calls `register_knowledge_poller(product_id)` for each. `register_knowledge_poller` re-reads the product with its sources and destinations, and returns early (`knowledge_poller_skipped`) when the product is missing, disabled, has no linked source, or has no enabled destination. Otherwise it starts the loop and fires one immediate `sync_knowledge_product(product_id)`.
- `resolved_interval_seconds(product)` decides the cadence: **live** mode is 3 s; else `sync_interval_seconds` floored at 5 s; else `sync_interval_minutes × 60` floored at 5 s; else 300 s.
- `sync_knowledge_product` guards on `_SYNCING_PRODUCTS`, so a burst of source events collapses into one running sync plus one waiting task. It sets the product `status = "syncing"`, calls `execute_universal_fanout_sync(db, product)`, then sets `status = "idle"`, `last_sync_at` and clears `error_message`, and writes the same on every enabled destination. On a failure it sets `status = "error"` with the message.
- Registration is re-invoked on create, update, a destination toggle, and pause-all / resume-all. A product with every destination paused stops polling; a single paused destination does not.
- `knowledge_events.publish` feeds the SSE stream from the same process. It is synchronous and runs on the event loop, never inside a destination worker thread.

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
| `litellm_base_url` | `http://host.docker.internal:4000` | embeddings, entity extraction, model listing; the destination field surface no longer declares it |
| `openai_api_key` | `sk-bot` | LiteLLM bearer token |
| `embedding_model` | `nvidia-embed-textonly` | default dense model for an Ingestion Profile |
| `multimodal_embedding_model` | `nvidia-embed-multimodal` | offered in the pipeline model dropdown; no ingestion path embeds an image directly, because a figure becomes a caption and the caption is embedded as text |
| `caption_model` | `groq-vision` | vision model that captions document figures, on `text_images` profiles |
| `image_min_pixels` | `10000` | a figure below this pixel count is skipped |
| `summary_model` | `Gpt-oss-20b` | chat model for RedisVL RAPTOR summaries; a small fast model, because it runs per file |
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
| `opensearch_username` / `opensearch_password` | `""` | OpenSearch basic auth; an empty username means no auth |
| `neo4j_*` (legacy) | — | `neo4j_bolt_uri`, `neo4j_http_url`, `neo4j_user`, `neo4j_password` and `neo4j_auth_disabled` stay declared in `settings.py`, but no destination reads them after 2026-09-20 |

Derived values: `embedding_model_options` (`embedding_model`, `multimodal_embedding_model`, `text-embedding-3-small`, `text-embedding-3-large`), `unique_embedding_models` (deduplicated), `async_database_url` (asyncpg URL).

Destination defaults that are not settings live in `apps/api/routes/knowledge_destination_schemas.py`, e.g. `bm25_k1 = 1.2`, `bm25_b = 0.75`, `hnsw_m = 16`, `hnsw_ef_construct = 100`, `number_of_shards = 1`, `number_of_replicas = 0`, `refresh_interval = "1s"`, `ttl_seconds = 86400`, `similarity_threshold = 0.85`. The catalogue returns exactly four entries with **15 fields, down from 43**.

The connection and secret fields left the surface on 2026-09-20, and `.env` supplies every connection value. The removed keys are `url`, `api_key`, `endpoint_url`, `auth_type`, `username`, `password`, `connection_url`, `redis_url`, `litellm_base_url`, `litellm_api_key`, `vector_size`, `distance`, `quantization`, `on_disk_payload`, `index_algorithm`, `distance_op`, and the per-destination `embedding_model`. The store-name keys `collection_name`, `index_name`, `schema_name` and `index_prefix` left the surface too, because a profile carries no store name.

`merge_destination_config()` merges user input over these defaults and `normalize_destination_payload()` drops unknown destination ids — it does not add implicit destinations. `apply_store_namespace()` assigns `kp_<slug>_<id8>` unconditionally and overwrites a stored value. `_validate_store_namespace()` rejects a clash between products with `422 DESTINATION_STORE_CONFLICT`, but the API can no longer reach it, because a store name is never taken from input. Only the product copy calls `apply_store_namespace()`. `hnsw_m` and `hnsw_ef_construct` reach `platform_common` and apply at collection creation.

---

## 9. Database Schema & Migrations

`src/shared/db/models.py` defines 16 tables:

| Table | Model | Purpose |
|---|---|---|
| `directories` | `Directory` | virtual workspace folders |
| `files` | `FileRecord` | file metadata, hash, status (`processing/synced/failed/deleted/duplicate`) |
| `sync_jobs` | `SyncJob` | upload/append/rename/delete jobs on the metadata store |
| `chunk_uploads` | `ChunkUpload` | resumable chunked upload sessions |
| `sources` | `Source` | external source + its dedicated MinIO bucket, monitor modes, metrics |
| `source_connectors` | `SourceConnector` | per-connector type/config/monitor mode |
| `pipeline_sources` | `PipelineSource` | M2M pipeline<->source link with per-link monitor config |
| `pipelines` | `Pipeline` | rag strategy, embedding config, chunking, scraper settings, `knowledge_product_id` |
| `pipeline_runs` | `PipelineRun` | run status, counters, scraper job ids |
| `indexed_files` | `IndexedFile` | per-pipeline indexing state keyed by `content_hash` (`file_id` or `source_id` + `file_key`); the pipeline indexer writes it, the fanout does not |
| `knowledge_products` | `KnowledgeProduct` | name, enabled, status, `monitor_mode`, `sync_interval_seconds` / `sync_interval_minutes`, nullable `ingestion_profile_id` (FK, `ondelete="SET NULL"`), `pipeline_fingerprint`, `error_message`, `last_sync_at` |
| `knowledge_product_sources` | `KnowledgeProductSource` | M2M product<->source (MinIO bucket) |
| `knowledge_product_destinations` | `KnowledgeProductDestination` | per-destination `enabled`, `config` (JSONB), `status`, `error_message`, `last_sync_at` |
| `knowledge_product_files` | `KnowledgeProductFile` | per-product fanout ledger: `(knowledge_product_id, source_id, file_key)` unique, `etag`, `size_bytes`, `content_hash`, `status`, `pages_indexed`, `destinations_synced`, `error_message`, `last_synced_at` |
| `ingestion_profiles` | `IngestionProfile` | reusable configuration: `name` unique, `description`, `enabled`, `chunk_size` (default `1000`), `chunk_overlap` (default `120`), `modality_mode` (`text` or `text_images`), `text_embedding_model`, `caption_model`, `image_min_pixels` |
| `ingestion_profile_destinations` | `IngestionProfileDestination` | per-destination `enabled` and `config` (JSONB) held by a profile, unique on `(ingestion_profile_id, destination_type)`; the config holds tuning and behaviour keys only |

`KnowledgeProduct.ingestion_profile` is `lazy="selectin"`, so a product load also loads its profile. A product with `ingestion_profile_id IS NULL` keeps its own destination rows and ingests as before; no data backfill ran.

`KnowledgeProduct.pipeline_fingerprint` is a hash of the chunk size, overlap, modality mode, embedding model, caption model and image threshold. `POST /{id}/apply-profile` purges and re-syncs every destination when that hash differs.

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
| `008_knowledge_store` | `008_knowledge_store.py` | created knowledge_profiles, knowledge_profile_sources, knowledge_destination_configs (all renamed in `010`) |
| `009_pipeline_knowledge_profile` | `009_pipeline_knowledge_profile.py` | added `pipelines.knowledge_profile_id` (renamed in `010`) |
| `010_knowledge_products` | `010_knowledge_products.py` | renamed the three knowledge tables, their indexes and columns; added `monitor_mode`, `sync_interval_seconds`, `sync_interval_minutes`; created `knowledge_product_files`; deleted the `graph_neo4j` destination rows and the `indexed_files` rows with `pipeline_id IS NULL` |

`models.py` also installs SQLite compilers for `JSONB`/`UUID` so the schema can be created on SQLite (used by tests). The SQLite dev database is created by `init_db()`, which runs `_ensure_sqlite_renames(path)` before `Base.metadata.create_all` and `_ensure_sqlite_columns(path)` after it, because `create_all` never renames a table.

**The two Ingestion Profile tables have no Alembic revision.** `Base.metadata.create_all` creates any table that does not exist, so the head stays `010_knowledge_products`. Three details go with them:

- The name `ingestion_profiles` is deliberate. Migration `008_knowledge_store` spent `knowledge_profiles` on the table that `010_knowledge_products` renamed to `knowledge_products`, so reusing that name would collide with the migration history.
- On SQLite the new column comes from the `_ensure_sqlite_columns` list in `src/shared/db/session.py`: `("knowledge_products", "ingestion_profile_id VARCHAR(36)")`. Without that entry every product read fails with `no such column`.
- The four modality columns are SQLite entries too: `modality_mode TEXT DEFAULT 'text'`, `text_embedding_model TEXT DEFAULT 'nvidia-embed-textonly'`, `caption_model TEXT` and `image_min_pixels INTEGER DEFAULT 10000`. Without them a local run fails with `no such column: ingestion_profiles.modality_mode`.

---

## 10. Ingestion & Fanout Pipeline (as implemented)

### 10.1 Metadata-store path (directories, pipelines, Qdrant)
1. Files enter a directory via `POST /api/uploads/init` -> `PUT .../chunks/{n}` -> `POST .../complete`, which enqueues a `file_manager:jobs` job; the worker moves the staged file into `storage/uploads/<directory>/<uuid-name>`, sets `stored_name`/`relative_path`, size, `content_hash` (from the job payload when present) and `status = synced`.
2. `POST /api/pipelines/{id}/sync` (or the cron job `sync_all_pipelines`) enqueues `ingestion:sync:jobs`; `sync_runner.sync_pipeline` builds the sets of new / changed / deleted files from a `PipelineRun`, the pipeline's `directory_names`, its linked source buckets, and the existing `indexed_files` rows (compared by `content_hash` and by `file_id` or `(source_id, file_key)`), then calls `FileIndexer` on the new and changed files and drops the deleted ones from the collection.
3. `indexer.py` splits page text with `chunk_text(chunk_size, chunk_overlap)`, embeds dense vectors through `EmbeddingClient` (LiteLLM `/v1/embeddings`, FastEmbed `BAAI/bge-small-en-v1.5` fallback) and sparse vectors when the strategy is `sparse`/`hybrid` (also for `multimodal`/`metadata` with text modality), then upserts points into the pipeline's Qdrant collection. Payloads carry `source_type="file_ingest"`, `source_id`, `source_locator`, `pipeline_id`, `file_id`, `directory_name`, `chunk_index`, `page_index`, `content`, `rag_strategy`, `embedding_model`.
4. `POST /api/pipelines/query` performs dense/sparse/hybrid search through `platform_common` Qdrant helpers.

### 10.2 Source path (connectors, fanout to the 4 destinations)
1. `POST /api/sources` creates a `Source` row with a deterministic MinIO bucket. A **NiFi connector source** (`source_type: "minio"`) starts with no connectors and gets them through `POST /api/sources/{id}/connectors`, where the type must be one of the three catalogue ids `google_drive`, `s3`, `azure_blob`. A **Manual Upload source** (`source_type: "minio_manual"`) writes files straight into its bucket through `POST /api/sources/{id}/files`. Legacy local filesystem rows still resolve to `local-<folder>`.
2. Manual sync (`POST /api/sources/{id}/sync`, `.../connectors/{cid}/sync`, file upload/delete, MinIO event webhook, or the cron/10-second poll) marks the source `syncing` and pushes `pathway_sync_queue`.
3. `pathway_worker` calls `pathway_sync.sync_source_from_pathway`, which runs the connector/dir sync into the source's MinIO bucket and then calls `_trigger_pipeline_syncs(db, source)`. That function starts `sync_knowledge_product(product_id)` for every linked Knowledge Product and enqueues a pipeline run per linked pipeline; it does not run the fanout itself.
4. A Knowledge Product (`knowledge_products`) links one or more sources (`knowledge_product_sources`) and one row per destination (`knowledge_product_destinations`). `monitor_mode` plus `sync_interval_seconds` / `sync_interval_minutes` decide its poll cadence. The destination rows are a **copy** of an Ingestion Profile taken when the product is created. The profile holds no store name, and the copy derives one as `kp_<slug>_<id8>`. See §10.3.
5. There is no manual sync route. `register_knowledge_poller(product_id)` starts the product's poller and fires one immediate sync. Each later tick calls `sync_knowledge_product(product_id)`. That function guards on `_SYNCING_PRODUCTS` and sets `status="syncing"`. It calls `execute_universal_fanout_sync(db, product)`, then sets `status="idle"`, `last_sync_at` and clears `error_message`. It writes the same on every enabled destination. On a failure it sets `status="error"` and keeps the message. The API host and the pathway worker both call this function, so it also takes a cross-process Redis lock (`knowledge:sync:lock:<product_id>`, TTL 900 s). A compare-and-delete script releases the lock, so one holder never deletes another holder's lock.
6. `execute_universal_fanout_sync(db, product)`:
   - resolves the product with sources and destinations loaded, keeps only enabled destinations and linked sources; with no enabled destination it returns zeros with `"message": "No destination is enabled."`;
   - per source, builds the set of live objects — `list_objects(bucket)` for MinIO, `storage/local_sources/<folder>.rglob("*")` for local sources — and loads the existing `KnowledgeProductFile` rows for `source_id` keyed by `file_key`;
   - compares the object's **etag and size** against the row: unchanged and already present in every enabled destination -> skipped without a download; changed -> purge the key from every destination in `destinations_synced` (a paused one included), then re-fanout; absent from the live set but present in `knowledge_product_files` -> purge from every destination that holds it, then delete the row;
   - downloads the object to a `tempfile.NamedTemporaryFile`, then `page_yielder.iter_file_pages(..., render_pages=False, include_figures=True)` yields `FilePage(page_index, text, image_png)` rows (PyMuPDF for PDF, python-docx, csv, json, plain text/markdown fallback). Extraction reads embedded image XObjects and never renders a page;
   - on a `text_images` profile, `_caption_pages()` turns each figure page into one caption and counts a failure in `images_skipped`. A caption page keeps `modality="image"` and its `image_ref`;
   - `_chunk_pages()` splits every page with the product's chunking and its **chunk strategy**, so the list that reaches the writers holds one `FilePage` per record. `page_index` is kept, and `chunk_index` is numbered from `0` inside each page. Each record also carries `record_type` (`chunk`, `parent` or `child`) and, for a child, `parent_ref` = `<page_index>:<parent chunk_index>`. `_assign_image_chunk_indexes()` offsets each figure past the text chunks of its own page, so two records never share a Redis key. A blank page yields no chunk;
   - `_embed_records()` fills one shared vector per record **once per tick**, before the writers run. `needs_vectors` is true when Qdrant is enabled, or when PostgreSQL stores embeddings;
   - fans out with `asyncio.gather(*[_fanout_to_destination(...) for dest in missing], return_exceptions=True)`, where each `_fanout_to_destination` offloads the synchronous writer via `asyncio.to_thread`;
   - updates the `KnowledgeProductFile` row: `destinations_synced` gains each destination that succeeded, plus `etag`, `size_bytes`, `content_hash`, `pages_indexed` and `last_synced_at`, and `status` becomes `synced` when every enabled destination holds the file, else `pending`. `pages_indexed` counts **source pages**, not chunks, so the UI `Pages` column keeps its meaning;
   - returns `{"status", "files_processed", "files_added", "files_updated", "files_deleted", "files_unchanged", "pages_processed", "destinations_synced", "images_skipped"}`.
7. Per-destination writes (all synchronous, REST/driver level, no driver pooling):
   - `vector_qdrant` — reuses the tick's shared vector. It calls `QdrantVectorStore.ensure_collection(<the product's kp_<slug>_<id8> collection>, <the embedding length>, enable_sparse=False, hnsw_m=…, hnsw_ef_construct=…)`, then `upsert_batch` with one point per chunk carrying the fanout payload, whose `chunk_index` is the real chunk number. The dimension comes from the data. The writer refuses to recreate an existing collection whose dimension disagrees, because a recreate would delete every point. `hnsw_m` and `hnsw_ef_construct` are the only destination keys this branch reads.
   - `lexical_opensearch` — `PUT {index_name}` with `number_of_shards` / `number_of_replicas` / `refresh_interval` index settings. The BM25 k1 and k2 values are **not** applied to the mapping. The writer indexes one document per chunk. The document carries `file_key`, `page_index`, `chunk_index`, `content`/`text`, `source_id`, `source_locator`, `created_at`, `modality`, `sparse_model`, `bm25_k1` and `bm25_b`. Basic auth uses `opensearch_username` and `opensearch_password`.
   - `relational_pgvector` — runs `CREATE SCHEMA IF NOT EXISTS` for the product's schema `kp_<slug>_<id8>`, then `CREATE EXTENSION IF NOT EXISTS vector`. It inserts one row per chunk into `<schema>.chunks` with `source_id`, `file_key`, `page_index`, `chunk_index`, `modality` and `content`. `chunk_index INT NOT NULL DEFAULT 0` is added to a table written by an older version with `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. When `store_embeddings` is enabled (default `True`) the row carries the shared dense embedding, otherwise text only. The vector column size is the embedding length. The writer also creates `USING hnsw (embedding vector_cosine_ops)`, and pgvector caps that index at 2000 dimensions. A wider model gets no index and a search becomes an exact scan. The purge runs `DELETE ... WHERE file_key = %s AND source_id = %s`.
   - `cache_redisvl` — writes one key per chunk as `"<prefix>:<source_id>:<file_key>:<page_index>:<chunk_index>"`, with a `:children` set and an optional `:summary` key. The prefix is the product's `kp:<slug>:<id8>`. The JSON value carries `chunk_index`, `modality` and `image_ref`. It honours `ttl_seconds` (default `86400`), `parent_child_mapping` (default `True`), a `similarity_threshold` stored in the payload, and optional RAPTOR summaries when `raptor_summaries` is enabled. The purge scans `"<prefix>:<source_id>:<file_key>*"` with glob metacharacters escaped.
8. `purge_knowledge_product()` (used by `DELETE /api/knowledge-products/{id}`) walks the product's linked `source_id`s, purges each tracked `file_key` from every destination that holds it, deletes the `KnowledgeProductFile` rows, and returns `{"purged_files", "source_ids", "destinations"}`. The API then stops the poller, clears the SSE buffer, and deletes the product row (destinations, source links and file rows cascade).

### 10.3 Ingestion Profiles (reusable destination and chunking configuration)

An **Ingestion Profile** (`ingestion_profiles` plus `ingestion_profile_destinations`) saves a destination set, the chunking parameters and the modality once, so several products reuse them. Router: `apps/api/routes/ingestion_profiles.py`, prefix `/api/ingestion-profiles`. Page: `IngestionProfilesPage`, route `/ingestion-profiles`; the full page walkthrough is document 06.

Three behaviours are settled:

1. **A product copies a profile; it is not a live reference.** `POST /api/knowledge-products` takes an optional `ingestion_profile_id`. When it is present it is authoritative and `req.destinations` is ignored: `_destinations_from_profile()` reuses `_prepare_destinations()` and writes one `KnowledgeProductDestination` row per profile destination. Editing a profile later does not touch a product that already exists. A caller that sends `destinations` and no profile keeps the old behaviour.
2. **Store names stay per product.** A profile carries no store name at all. The copy assigns `kp_<slug>_<id8>` to every destination and overwrites any stored value. Two products over one profile therefore write to separate stores and keep separate ledgers.
3. **`POST /api/knowledge-products/{id}/apply-profile` re-copies on demand.** The body may carry an `ingestion_profile_id`, and without it the product's stored link is used. A product with no link answers `422 PROFILE_REQUIRED`. The route compares the product's `pipeline_fingerprint` with the profile's. When the hash differs, every destination is purged and re-synced, because a chunking or modality change alters what is written. A change to one destination config alone purges that destination only. The route deletes the removed destination rows, updates the changed ones and inserts the new ones. It re-registers the poller and returns `{status, profile_id, profile_name, added, updated, removed, purged_files}`.

The profile carries four modality columns: `modality_mode` (`text` or `text_images`, default `text`), `text_embedding_model` (one model for every destination), `caption_model` (nullable) and `image_min_pixels` (default `10000`).

| mode | what the fanout reads | vision model |
|---|---|---|
| `text` | selectable text and tables only | none |
| `text_images` | the same, plus one caption per embedded figure | `caption_model` |

The vector dimension is **derived** from the embedding-model output, so no profile or destination field declares it. The fanout embeds each chunk once per tick and shares the vector with every vector destination.

Profile CRUD rules: `name` is unique, and a duplicate answers `400`. `chunk_overlap` must stay below `chunk_size` on both `POST` and `PATCH`, and a violation answers `422 CHUNK_OVERLAP_TOO_LARGE`. A `text_images` profile without a caption model answers `422 CAPTION_MODEL_REQUIRED`. A supplied `destinations` list replaces the whole set. `DELETE` answers `409 PROFILE_IN_USE` with `product_count` while a product references the profile. Deleting is blocked on purpose, because the FK is `SET NULL`. A delete would leave the products with copied rows and no way to reach the profile again.

The Knowledge Store create/edit dialog no longer collects destination configuration. It asks for a name, a description, an **Ingestion Profile** select with a read-only summary, the sync mode and the MinIO sources. The schedule stays on the product. A product created before this feature has no profile and shows the `Legacy: inline config` badge. The product detail page shows `Profile: <name>`, `Chunk <size> / <overlap>`, `Chunking: <strategy>` and `Modality: Text + images` badges and an **Apply Profile** button.

Chunking reads the profile through `_resolve_chunking(product)`: a product with no profile falls back to `1000 / 120`, and the overlap is clamped to `chunk_size - 1`. The strategy comes from `_resolve_chunk_strategy(product)`, which defaults to `recursive`. The modality comes from `_resolve_modality_mode(product)`. See §10.2 step 6 for where the split happens.

### 10.4 Ingestion pipeline stages

Every file runs six stages in one tick:

1. **Text extraction** — `page_yielder.iter_file_pages()` reads PyMuPDF text for a PDF, python-docx for a DOCX, and csv, json or plain text directly. The fanout passes `render_pages=False`, so no page becomes a PNG.
2. **Figure extraction** — with `include_figures=True`, each embedded PDF image XObject becomes a `FilePage` with `modality="image"` and an `image_ref` of `{page_index, image_index}`. A figure below `image_min_pixels` is dropped here, so a logo or a rule never becomes a chunk.
3. **Captioning** — on a `text_images` profile one vision call sends the figure to `caption_model`, and the reply replaces the image bytes as the page text. The stack uses vision captions and **does not implement OCR**. A scanned page has no text layer, so `text` mode yields no chunk for it and `text_images` mode captions its page image. A failed caption drops that figure and counts in `images_skipped`.
4. **Chunking** — `_chunk_pages()` splits every page with `chunk_size`, `chunk_overlap` and the profile's `chunk_strategy`. Each figure page then gets a `chunk_index` above the text chunks of its own page. `context_aware` runs here too: one batch embedding call per page finds the topic shifts, and the whole split runs in a worker thread.
5. **One shared embedding pass** — `_embed_records()` calls the embedding client **once per chunk per tick** and stores the vector on the `ChunkRecord`. The Qdrant and PostgreSQL writers reuse that vector, so no chunk is embedded twice.
6. **Fanout** — the four writers run in parallel through `asyncio.gather`, and each one reads the shared record for its text, payload and vector.

---

## 11. Key Engineering Invariants
1. **Metadata-based differential ingestion (fanout)**: `KnowledgeProductFile` rows are unique on `(knowledge_product_id, source_id, file_key)`. The fanout skips an object whose ETag and size are unchanged since the last tick and whose row is already synced into every enabled destination. A changed file is purged from every destination that holds it before re-indexing. A removed file is purged and its row deleted. The pipeline path keeps its own `IndexedFile` rows keyed by `(pipeline_id, content_hash)` and `(pipeline_id, source_id, file_key)`, where source file identity stays the SHA-256 of the object bytes.
2. **Parallel fanout with per-destination failure recording**: destinations are written concurrently (`asyncio.gather(..., return_exceptions=True)` over `asyncio.to_thread` calls), so one failing destination does not abort the others. Every writer re-raises. A failure is left out of `destinations_synced`, written to the row's `error_message`, published as `destination_failed` on the SSE stream, and leaves the file `status = "pending"`, so the next tick retries only the missing destination. It is never reported as success.
3. **Retrieval-aligned payloads**: fanout documents carry `source_type`, `source_id`, `source_locator`, `file_key`, `file_name`/`original_name`, `page_index`, `chunk_index`, `modality`, `image_ref`, `content`/`text`, `knowledge_product_id`, and `created_at`; the pipeline indexer emits `source_type="file_ingest"`, `source_locator="<directory>/<file>#page-<n>"`, plus pipeline/strategy/embedding metadata for `platform_common` hit mapping.
4. **Product delete purge**: `DELETE /api/knowledge-products/{id}` purges indexed artifacts from every destination that holds them before deleting the product, and returns a `purge_summary`.
5. **Live inspectability**: `GET /api/knowledge-products/{id}/inspect/{destination_type}` serves live read-back data for all four destinations. The `vector_qdrant` panel shows collection info and a scroll of points with a pseudo-3D projection. The `lexical_opensearch` panel shows match-all hits and aggregated term frequencies. The `relational_pgvector` panel shows rows from the product's schema. The `cache_redisvl` panel shows keys under the product's prefix. Every inspector returns `modality` and, where the store holds it, `image_ref`.
6. **Single API-key gate**: every route is behind `verify_api_key` (header or query param), disabled only when `api_key` is empty.
7. **Profile copy, not live reference**: a Knowledge Product stores its own `KnowledgeProductDestination` rows. They are copied from the linked Ingestion Profile at create time, or again by `POST /{id}/apply-profile`. Store names are per product (`kp_<slug>_<id8>`) and a profile carries none, so two products can share one profile and stay isolated. Editing a profile never changes an existing product. The re-apply purges the destinations it removes or changes, and it purges all four when the `pipeline_fingerprint` changed.
8. **One embedding per chunk, one sync per product cluster-wide**: the fanout embeds a chunk once per tick and shares the vector with every vector destination. It also asserts that every vector in a batch has the same length. `sync_knowledge_product` takes a cross-process Redis lock, so the API poller and the pathway worker cannot fan out the same file twice.

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
| `postgres` | `pgvector/pgvector:pg16` | — | `5432:5432` |
| `neo4j` | (declared in `docker-compose.yaml`) | — | `7474:7474`, `7687:7687` (unused by any destination since 2026-09-20) |
| `otel-collector` | `otel/opentelemetry-collector:0.148.0` | — | `4317:4317`, `4318:4318` |
| `rag-migrate` / `rag-api` / `eval-worker` (+ guardrails services) | retrieval Dockerfile on this compose file | — | `8001:8001` (`rag-api`) |

Shared volumes: `file_storage` (`api`, `worker`, `pathway-worker` mount it at `/app/storage`), `hf-cache` (`worker` and the retrieval `rag-api`), `minio_data`, `pg_data`, `qdrant_data`, `neo4j_data` (still declared, unused by any destination), `nifi_data`, `scraper_data`. All ingestion services set `extra_hosts: host.docker.internal:host-gateway`, so the LiteLLM base URL setting can point at a host-run proxy.

---

## 13. Verification
- E2E: `backend/scripts/e2e_knowledge_fanout.py` (two products over one bucket, store-name isolation, a supplied store name overwritten by the derived one, add/replace/delete propagation to all four destinations, `POST /sync` returns 404) and `backend/scripts/e2e_knowledge_pause.py` (pause-all, resume-all, per-destination pause).
- E2E profiles: `backend/scripts/e2e_ingestion_profiles.py` runs against the live API and the four stores. It proves that a profile carries no store name while the product copy gets `kp_*`. It also proves that one source page becomes many documents, and that a larger `chunk_size` yields one document. A config change through `apply-profile` moves a store, and `409 PROFILE_IN_USE` guards a delete.
- E2E modality: `backend/scripts/e2e_ingestion_modality.py --source-id <uuid>` proves several facts. The field surface holds no connection or dimension key. The derived dimension reaches Qdrant. `text` mode stores no image document, and `text_images` stores one caption in every store. A `text_images` profile without a caption model answers `422 CAPTION_MODEL_REQUIRED`.
- E2E chunk strategies: `backend/scripts/e2e_chunk_strategies.py --source-id <uuid>` moves one product through `section`, `parent_child`, `fixed` and `context_aware`. After each change it reads all four stores and proves the record count matches the strategy, that every child names a parent stored beside it, that a strategy change leaves no stale `record_type` behind, and that the stores agree on the count. It also proves that an unknown strategy name is a `422`.
- Legacy cleanup: `backend/scripts/purge_neo4j_legacy.py` deletes the `Chunk`/`Document`/`Entity` nodes written before the graph destination was removed.
- Tests: `backend/tests/test_page_yielder.py`, `test_page_yielder_figures.py`, `test_fanout_payload.py`, `test_knowledge_destination_schemas.py`, `test_knowledge_product_files.py`, `test_connector_config_validation.py`, `test_ingestion_profile_chunking.py` and `test_ingestion_modality_resolvers.py`. Chunking covers `_resolve_chunking` and `_resolve_chunk_strategy` with no profile and with one, an overlap above the size, `_chunk_pages` over one long page, a blank page and three pages, and every one of the seven strategies, including that a child record's `parent_ref` resolves to a `parent` record. Run with `uv run pytest tests -q` from `rag-ingestion-manager/backend`. 23 cases preceded this feature.
