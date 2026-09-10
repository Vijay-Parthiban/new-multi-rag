# rag-ingestion-manager — Detailed System Documentation

## 1. Executive Summary & Application Scope

The **`rag-ingestion-manager`** is a dedicated full-stack management application focused on document ingestion, directory navigation, automatic live & scheduled connector synchronization, multi-sink Knowledge Store profile management, and chunked resumable file uploads.

- **Frontend UI Port**: `5173` (`http://localhost:5173`)
- **Backend API Port**: `8007` (`http://localhost:8007`)
- **Vite Proxy Rule**: `/api` -> `http://127.0.0.1:8007`
- **Domain Boundary**: Focused on ingestion operations, directory management, data sources, knowledge store fanout, and upload management.

---

## 2. Navigation Structure

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 RAG INGESTION MANAGER UI (5173)                             │
├───────────────────┬─────────────────────────────────────────────────────────────────────────┤
│ Sidebar / Tab     │ Route Path & Description                                                │
├───────────────────┼─────────────────────────────────────────────────────────────────────────┤
│ 1. Overview       │ /                  - Key ingestion metrics & system health summary      │
│ 2. Folders        │ /browse            - Virtual directory structure & MinIO file browser   │
│ 3. Sources        │ /sources           - Data source CRUD, automatic live & scheduled sync  │
│ 4. Knowledge Store│ /knowledge-store   - Multi-source to 5 multi-destination fanout engine   │
├───────────────────┼─────────────────────────────────────────────────────────────────────────┤
│ Auxiliary Pages   │ Route Path & Description                                                │
├───────────────────┼─────────────────────────────────────────────────────────────────────────┤
│ Quick Upload      │ /upload            - Resumable 5MB chunked document uploader            │
│ Source Detail     │ /sources/:id       - Detailed connector config, files, & sync controls  │
└───────────────────┴─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Core Technical Architecture & Data Engine

### 3.1. Data Source Synchronization Engine (`pathway_sync.py`)
- **Automatic Live & Scheduled Background Polling**:
  - **Live Mode**: Instantaneous background polling loop with a 3-second continuous sleep interval (<5s latency).
  - **Scheduled Mode**: Precise background polling loop executing every `connector_sync_interval_minutes` or connector `sync_interval_minutes`.
- **FastAPI Lifespan Startup**: Pollers start automatically on server startup via `init_all_source_pollers()` called within `lifespan` in `apps/api/main.py`.
- **Dynamic Lifecycle Management**:
  - `register_source_poller(source_id)`: Inspects monitor modes across source and attached connectors, stops any existing poller task, spawns the appropriate continuous poller loop in `_SOURCE_POLLER_TASKS`, and enqueues an immediate initial sync (`_trigger_initial_sync`).
  - `stop_source_poller(source_id)`: Cancels active poller tasks upon source deletion or disablement.
- **Manual Trigger**: Manual "Sync Now" API endpoint (`POST /api/sources/{id}/sync`) remains active for explicit on-demand syncs.

### 3.2. Universal Multi-Sink Fanout Engine (`universal_fanout.py`)
Distributes documents from source MinIO buckets across 5 destination categories:
1. **Vector Engine**: Qdrant Vector DB (Dense + BM25 sparse vectors).
2. **Lexical Engine**: OpenSearch (BM25 + SPLADE).
3. **Knowledge Graph Store**: Neo4j (Entity-relation triplets).
4. **Relational Database**: PostgreSQL (`pgvector` / `pgvectorscale`).
5. **Semantic Cache & Summary**: RedisVL (RAPTOR tree structures).

---

## 4. Database Schema & Data Models

### 4.1. `sources` & `source_connectors`
- `sources`: Primary record storing `name`, `minio_bucket`, `connector_monitor_mode` (`live` | `scheduled`), `connector_sync_interval_minutes`, `pipeline_monitor_mode`, `enabled`, `last_sync_at`, and `status`.
- `source_connectors`: Attached connectors (`connector_type`, `config`, `monitor_mode`, `sync_interval_minutes`, `enabled`, `status`).

### 4.2. `directories` & `files`
- `directories`: Virtual directory hierarchy (`name`, `description`).
- `files`: Ingested document records (`display_name`, `file_hash`, `file_size_bytes`, `mime_type`, `minio_key`).

### 4.3. `knowledge_profiles` & `knowledge_profile_sources`
- `knowledge_profiles`: Multi-destination fanout configuration (`name`, `destinations`, `enabled`).
- `knowledge_profile_sources`: Join model linking Knowledge Profiles to data sources.
