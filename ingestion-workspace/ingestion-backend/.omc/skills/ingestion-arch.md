---
name: ingestion-arch
description: Ingestion backend architecture — sources, pipelines, Pathway/airbyte sync, RAG indexing
model:
  temperature: 0.1
---

# Ingestion Backend Architecture

## Overview
FastAPI + SQLAlchemy async backend for a multi-RAG pipeline ingestion system. Manages external data sources (Airbyte/Pathway connectors), file indexing, and RAG pipeline execution with Qdrant vector storage.

## Key Files

### API Layer
- `apps/api/main.py` — FastAPI app, CORS, lifespan, 5 routers, /health
- `apps/api/routes/sources.py` — Source CRUD (15 connector types), link/unlink pipelines, sync trigger, file listing
- `apps/api/routes/pipelines.py` — Pipeline CRUD, RAG query (POST /api/pipelines/query), stats, sync trigger

### Workers
- `apps/worker/main.py` — Main async worker: polls 3 Redis queues (file_manager > pipeline > sync), starts APScheduler
- `apps/pathway_worker/main.py` — Dedicated worker: polls `pathway:sync:jobs`, calls `sync_source_from_pathway()`
- `apps/worker/scheduler.py` — APScheduler cron (default */10 min) for `sync_all_enabled_sources` + `sync_all_pipelines`

### Core Logic
- `src/ingestion_service/core/pathway_sync.py` — Sync source via Pathway Airbyte connector, write to MinIO, trigger pipeline re-index
- `src/ingestion_service/core/sync_runner.py` — Idempotent diff-based file sync (new/changed/deleted), 315 lines
- `src/ingestion_service/core/pipeline_runner.py` — Pipeline run: downloads files from MinIO, indexes page-by-page
- `src/ingestion_service/core/indexer.py` — FileIndexer: chunk → embed (dense + sparse) → upsert to Qdrant
- `src/ingestion_service/clients/source_sync.py` — `trigger_source_sync()` + `sync_all_enabled_sources()`

### Shared
- `src/shared/db/models.py` — 10 SQLAlchemy models, all enums (FileStatus, JobStatus, RagStrategy, etc.)
- `src/shared/db/session.py` — Lazy async engine, get_db() for FastAPI Depends
- `src/shared/db/migrate.py` — Alembic runner with 30 retries
- `src/shared/queue/client.py` — Redis singleton, 8 queue functions (BRPOP/LPUSH)
- `src/shared/config/settings.py` — 50+ env vars, async_database_url property
- `src/shared/storage/s3_client.py` — Async MinIO client via aioboto3

## Data Models (SQLAlchemy)

### Source
- Fields: name, connector_type, config (JSONB), monitor_mode (LIVE/SCHEDULED), minio_bucket, sync_interval_minutes, enabled, last_sync_at, status (disconnected/syncing/connected/error), error_message
- M2M with Pipeline via PipelineSource (CASCADE deletes)

### Pipeline
- Fields: name, description, rag_strategy (naive/sparse/hybrid/multimodal/metadata), index_modality, embedding_model, dense_top_k, sparse_top_k, chunk_size, chunk_overlap, etc.
- Has many PipelineRun + IndexedFile records
- Has many Source (via PipelineSource)
- Has many Directory (via FileRecord)

### Key Enums
- RagStrategy: naive, sparse, hybrid, multimodal, metadata
- IndexModality: text, image, text_and_image
- SourceMonitorMode: live, scheduled

## Redis Queues (4)
1. `file_manager:jobs` — highest priority
2. `ingestion:pipeline:jobs` — pipeline run queue
3. `ingestion:sync:jobs` — sync run queue
4. `pathway:sync:jobs` — pathway source sync queue

## MinIO Layout
- `{prefix}-{pipeline-name}-{id[:8]}` — per-pipeline buckets
- `{prefix}-{source-name}-{id[:8]}` — per-source buckets
- prefix defaults to "rag-content"
- Files stored at: `{bucket}/{directory_uuid}/{filename}`

## API Endpoints

### Sources (`/api/sources`)
- GET /connectors — list 15 connector options
- GET / — list all sources
- POST / — create source (auto-creates MinIO bucket + triggers sync)
- GET /{id} — get source
- PATCH /{id} — update source
- DELETE /{id} — delete source (must unlink pipelines first)
- POST /{id}/pipeline/{pid} — link to pipeline
- DELETE /{id}/pipeline/{pid} — unlink from pipeline
- GET /{id}/files — list files in source's MinIO bucket
- POST /{id}/sync — trigger sync via Pathway

### Pipelines (`/api/pipelines`)
- GET / — list all pipelines
- POST / — create pipeline
- GET /{id} — get pipeline
- PATCH /{id} — update pipeline
- DELETE /{id} — delete pipeline
- POST /{id}/sync — trigger file sync
- POST /{id}/run — trigger pipeline run
- POST /{id}/query — RAG query with metadata filters
- GET /{id}/stats — query stats
- POST /{id}/cancel — cancel running pipeline

## RAG Query Filters
POST /api/pipelines/query supports filter by: source_type, source_id, pipeline_id, file_id, directory_name, original_name, mime_type, rag_strategy

## Configuration (env vars)
- DATABASE_URL (default: postgresql://ingestion:ingestion@localhost:5433/ingestion)
- REDIS_URL (default: redis://localhost:6379/0)
- QDRANT_* — host/api_key/collection_name/dimensions
- MINIO_* — endpoint/access_key/secret_key/region/bucket_prefix
- SYNC_CRON_* — year/month/day/week/dow/hour/minute/second (default */10 min)
- EMBEDDING_MODEL (default: jinaai/jina-embeddings-v2-base-en)
- LITELLM_BASE_URL / OPENAI_API_KEY

## Commands
```sh
# Run
uvicorn apps.api.main:app --host 0.0.0.0 --port 8000
python -m apps.worker.main
python -m apps.pathway_worker.main
python -m src.shared.db.migrate

# Test/Lint
pytest
ruff check
```

## Docker
See `docker-compose.yaml` for full stack: api, worker, pathway-worker, web, scraper-api, scraper-worker, minio, qdrant, redis, postgres, rag-api, eval-worker
