# Comprehensive Multi-RAG Platform Architecture & System Documentation

## 1. Executive Summary & Platform Overview

The **Multi-RAG Platform** is an enterprise-grade, multi-workspace Retrieval-Augmented Generation (RAG) and document intelligence ecosystem. It integrates asynchronous multi-source document ingestion (Google Drive, Amazon S3, Azure Blob, Google Sheets, Databases, Web Scrapers, Confluence, SFTP), Apache NiFi external connectors, Pathway real-time continuous vector sync pollers, vector database indexing (Qdrant), hybrid retrieval & reranking, LLM orchestration, AI guardrails moderation, and a **Universal Multi-Sink Fanout Ingestion Engine** routing MinIO document buckets into 5 enterprise 2026 RAG destination categories.

### Three Core Workspaces
1. **`ingestion-workspace`**: Full-stack web frontend (React/TypeScript/Vite on port `5173`) and Ingestion API backend (FastAPI on port `8007`). Handles file uploads, directory watchers, Apache NiFi external connector syncs, Celery background indexing workers, Pathway continuous vector pollers, and the **Knowledge Store Manager** (`/knowledge-store`).
2. **`web-scrapper-workspace`**: Crawl4AI web scraper API (FastAPI on port `8000`) and shared infrastructure orchestrator (PostgreSQL `5432`, Redis `6379`, MinIO `9000/9001`, Qdrant `6333/6334`).
3. **`rag-app-workspace`**: RAG Query Engine & Evaluation API backend (FastAPI on port `8001`). Handles hybrid vector retrieval (dense embeddings + BM25 sparse text), cross-encoder reranking, LLM answer synthesis, Ragas/DeepEval offline evaluation execution, and guardrails trace moderation.

---

## 2. High-Level Architecture Topology

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                      Ingestion Frontend (React / Vite UI)                        │
│                                  Port: 5173                                      │
└───────────┬──────────────────────────────┬──────────────────────────────┬────────┘
            │                              │                              │
            │ Ingestion / Knowledge API    │ Scraper API                  │ RAG Query / Eval API
            v                              v                              v
┌────────────────────────┐      ┌────────────────────────┐      ┌────────────────────────┐
│ Ingestion API (FastAPI)│      │ Web Scraper (FastAPI)  │      │ RAG Query API (FastAPI)│
│       Port: 8007       │      │       Port: 8000       │      │       Port: 8001       │
└───────────┬────────────┘      └───────────┬────────────┘      └───────────┬────────────┘
            │                              │                              │
            ├──────────────────────────────┼──────────────────────────────┤
            │                              │                              │
            v                              v                              v
┌────────────────────────┐      ┌────────────────────────┐      ┌────────────────────────┐
│  MinIO Storage (S3)    │      │ PostgreSQL DB (5432)   │      │ Redis Cache & Queue    │
│  Per-Source Buckets    │      │ Knowledge & RAG Tables │      │ Celery / Cache (6379)  │
└───────────┬────────────┘      └───────────┬────────────┘      └───────────┬────────────┘
            │                              │                              │
            └──────────────────────────────┼──────────────────────────────┘
                                           │
                                           v
            ┌────────────────────────────────────────────────────────────┐
            │       Universal 2026 RAG Multi-Sink Fanout Engine          │
            ├──────────────┬─────────────┬─────────────┬─────────────────┤
            │              │             │             │                 │
            v              v             v             v                 v
     ┌─────────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐   ┌───────────────┐
     │   Qdrant    │ │ OpenSearch│ │  Neo4j    │ │PostgreSQL │   │    RedisVL    │
     │ Vector DB   │ │ Lexical   │ │ GraphRAG  │ │ (pgvector)│   │Semantic Cache │
     │ (Port 6333) │ │(Port 9200)│ │(Port 7687)│ │(Port 5432)│   │  (Port 6379)  │
     └─────────────┘ └───────────┘ └───────────┘ └───────────┘   └───────────────┘
```

---

## 3. Knowledge Store Manager & 5-Sink Fanout Architecture

The **Knowledge Store Manager** (`/knowledge-store`) decouples source document collection from destination vector & graph indexing. Users create **Knowledge Profiles** that group one or more isolated MinIO source buckets and map them to 5 enterprise 2026 RAG destination categories.

### 5 Enterprise Destination Categories
1. **Vector Engine (Qdrant)**: Stores 2048-dimensional dense vector embeddings using HNSW graph indexing and scalar/binary quantization (`knowledge_qdrant_collection`).
2. **Lexical & Sparse Search Engine (OpenSearch)**: Handles BM25 keyword matching and SPLADE/BGE-M3 learned sparse vector inverted indexing (`knowledge_lexical_index`).
3. **Knowledge Graph Store (Neo4j)**: Performs entity-relationship extraction and builds community report summaries for GraphRAG (`bolt://localhost:7687`).
4. **Multi-Model Relational Database (PostgreSQL with pgvector/pgvectorscale)**: Provides co-located document metadata, ownership ACLs, and vector embedding tables (`knowledge_vector_records`).
5. **Semantic Cache & Summary Stores (RedisVL)**: Manages parent-child chunk mappings, RAPTOR summary trees, and prompt semantic caching (`knowledge_cache`).

---

## 4. Source Connectors & Pathway Continuous Workers

### 4.1 Google Drive NiFi Source Sync
- **Connector Type**: `google_drive`
- **Authentication**: Google Cloud Service Account JSON key (`sanguine-robot-499610-q7-b777bdf1ad75.json`).
- **Target Folder**: Google Drive Folder ID `14IXHBDpExTdBDfh5GTKmQEIiv6AYHRMG` containing document sets (e.g. PDF resume files).
- **MinIO Storage**: Files are synchronized into dedicated per-source MinIO buckets (e.g. `source-gdrive-nifi-source-1788811754-4fdd6039`).

### 4.2 Pathway Continuous Vector Poller (`apps/pathway_worker/main.py`)
- Continuously monitors MinIO source buckets in real time using Pathway's streaming engine.
- Extracts document text, splits chunks, computes dense embeddings, and automatically upserts vectors into Qdrant collection `gdrive_nifi_pathway_collection`.

---

## 5. Shared Data Contracts & Database Schema

### 5.1 Alembic Migration `008_knowledge_store.py`
- `knowledge_profiles`: Stores profile ID, name, description, enabled status, sync status (`syncing`, `success`, `error`), and `last_sync_at`.
- `knowledge_profile_sources`: Junction table linking `knowledge_profiles` to `sources` (MinIO source buckets).
- `knowledge_destination_configs`: Configuration table holding destination type (`vector_qdrant`, `lexical_opensearch`, `graph_neo4j`, `relational_pgvector`, `cache_redisvl`), enabled status, configuration JSON, and sync timestamps.

---

## 6. Environment Setup & Deployment Guide

### 6.1 System Prerequisites
- **Docker**: Docker Engine 24.0+ & Docker Compose v2.20+
- **Node.js**: Node v18+ & npm 9+
- **Python**: Python 3.11+
- **Git**: Git 2.34+

### 6.2 Environment Variables Configuration

#### Shared Infrastructure (`web-scrapper-workspace/.env`)
```ini
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=rag_platform
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

REDIS_HOST=redis
REDIS_PORT=6379

MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin
MINIO_ENDPOINT=http://minio:9000

QDRANT_HOST=qdrant
QDRANT_PORT=6333
QDRANT_API_KEY=qdrant
```

#### Ingestion Backend (`ingestion-workspace/ingestion-backend/.env`)
```ini
PORT=8007
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/rag_platform
REDIS_URL=redis://localhost:6379/0
MINIO_ENDPOINT=http://localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_API_KEY=qdrant
RAG_API_URL=http://localhost:8001
SCRAPER_API_URL=http://localhost:8000
```

#### Ingestion Frontend (`ingestion-workspace/ingestion-frontend/.env`)
```ini
VITE_API_URL=http://localhost:8007
VITE_RAG_API_URL=http://localhost:8001
VITE_SCRAPER_API_URL=http://localhost:8000
```

---

## 7. Step-by-Step Installation & Running Guide

### Step 1: Start Shared Infrastructure Containers
```bash
cd web-scrapper-workspace
docker-compose up -d --build
```
*Verify containers are healthy (`postgres`, `redis`, `minio`, `qdrant`):*
```bash
docker-compose ps
```

### Step 2: Database Migration
```bash
cd ../ingestion-workspace/ingestion-backend
# Activate virtual environment
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
alembic upgrade head
```

### Step 3: Launch Ingestion Backend Containers & Services
```bash
cd ../
docker-compose up -d --build
```
*Or sync code updates directly to the running API container:*
```bash
docker cp ingestion-workspace/ingestion-backend/apps/api/routes/knowledge.py ingestion-workspace-api-1:/app/apps/api/routes/knowledge.py
docker cp ingestion-workspace/ingestion-backend/src/ingestion_service/core/universal_fanout.py ingestion-workspace-api-1:/app/src/ingestion_service/core/universal_fanout.py
docker exec ingestion-workspace-api-1 find /app -name "__pycache__" -exec rm -rf {} +
docker restart ingestion-workspace-api-1
```

### Step 4: Launch Frontend Dev Server
```bash
cd ingestion-frontend
npm install
npm run dev
```
*Open web interface at `http://localhost:5173/knowledge-store`.*

### Step 5: Test & Verify Ingestion
1. **Google Drive Sync**: Navigate to `/sources` and trigger sync for Google Drive connector.
2. **Knowledge Store Manager**: Navigate to `/knowledge-store`, click **Test Connection** for Qdrant, and click **Sync All Sinks**.
3. **Verify Vector Indexing**: Inspect Qdrant collections at `http://localhost:6333/dashboard` to confirm vectors are indexed in `knowledge_qdrant_collection`.
