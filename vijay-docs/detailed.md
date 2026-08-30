# Comprehensive Multi-RAG Platform Architecture & System Documentation

## 1. Executive Summary & Platform Overview

The Multi-RAG Platform is an enterprise-grade, multi-workspace Retrieval-Augmented Generation (RAG) and document intelligence ecosystem. It integrates asynchronous multi-source document ingestion, web content scraping, vector database indexing (Qdrant), hybrid retrieval & reranking, LLM orchestration, AI guardrails moderation, and real-time observability tracing.

The platform consists of three core execution workspaces:
1. **`ingestion-workspace`**: Full-stack web frontend (React/TypeScript/Vite on port `5173`) and Ingestion API backend (FastAPI on port `8007`). Handles file uploads, directory watchers, Apache NiFi external connector syncs (Google Drive, S3, Azure Blob, Google Sheets, Databases, Web Scrapers, Confluence, SFTP) into MinIO per-source buckets, Celery background indexing workers, and Pathway real-time continuous MinIO vector sync poller workers.
2. **`web-scrapper-workspace`**: Crawl4AI web scraper API (FastAPI on port `8000`) and shared infrastructure orchestrator (PostgreSQL `5432`, Redis `6379`, MinIO `9000/9001`, Qdrant `6333/6334`).
3. **`rag-app-workspace`**: RAG Query Engine & Evaluation API backend (FastAPI on port `8001`). Handles hybrid vector retrieval (dense embeddings + BM25 sparse text), cross-encoder reranking, LLM answer synthesis, Ragas/DeepEval offline evaluation execution, and guardrails trace moderation.

---

## 2. High-Level Architecture Topology

```
┌────────────────────────────────────────────────────────────────────────┐
│                   Ingestion Frontend (React / Vite)                    │
│                             Port: 5173                                 │
└───────┬─────────────────────────┬──────────────────────────┬───────────┘
        │                         │                          │
        │ API Requests            │ Scraper Requests         │ RAG Query & Eval
        v                         v                          v
┌───────────────┐         ┌───────────────┐          ┌───────────────┐
│ Ingestion API │         │ Web Scraper   │          │ RAG Query API │
│  (FastAPI)    │         │  (FastAPI)    │          │  (FastAPI)    │
│  Port: 8007   │         │  Port: 8000   │          │  Port: 8001   │
└───────┬───────┘         └───────┬───────┘          └───────┬───────┘
        │                         │                          │
        ├─────────────────────────┼──────────────────────────┤
        │                         │                          │
        v                         v                          v
┌───────────────┐         ┌───────────────┐          ┌───────────────┐
│ MinIO Storage │         │ PostgreSQL DB │          │ Redis Queue   │
│  Port: 9000   │         │  Port: 5432   │          │  Port: 6379   │
└───────┬───────┘         └───────┬───────┘          └───────┬───────┘
        │                         │                          │
        └─────────────────────────┼──────────────────────────┘
                                  │
                                  v
                       ┌────────────────────┐
                       │ Qdrant Vector DB   │
                       │ Port: 6333 / 6334  │
                       └────────────────────┘
```

---

## 3. Workspace Component Breakdown

### 3.1 `ingestion-workspace`
- **Frontend (`ingestion-frontend`)**: React 18, Vite, TypeScript, Lucide Icons, React Router v6. Single-Page Application (SPA) providing 11 distinct operational views:
  - Overview / Dashboard
  - Folders & Directory File Browser
  - Data Sources & Connector Catalogue
  - Document Upload & Ingestion
  - RAG Pipelines Management
  - RAG Chat Assistant & Playground
  - Prompts Management
  - Real-Time Performance Monitoring
  - Offline Evaluation & Golden Dataset Benchmark
  - Tracking & Telemetry Tracing
  - AI Guardrails Configuration, Tracing & Evaluation
- **Backend API (`ingestion-backend`)**: Python 3.11 FastAPI service managing pipelines, source connectors, file storage buckets, parsing, chunking, and worker tasks.
- **Celery Worker**: Asynchronous queue worker processing document parsing (PDF, DOCX, TXT, HTML, Markdown), text chunking, embedding generation, and Qdrant collection upserts.
- **Pathway Worker**: Continuous real-time Change Data Capture (CDC) worker monitoring external source connectors.

### 3.2 `web-scrapper-workspace`
- **Scraper API**: FastAPI service utilizing Crawl4AI to execute headless Playwright crawls, extract markdown/text, chunk contents, generate embeddings, and write directly into Qdrant collections.
- **Docker Compose Infrastructure**: Shared PostgreSQL database (relational metadata, pipelines, connectors, evaluations), Redis (Celery task broker & pub/sub), MinIO (S3-compatible object storage), and Qdrant (vector database).

### 3.3 `rag-app-workspace`
- **RAG Engine API**: FastAPI service serving hybrid vector search queries (`/api/v1/query`), LLM generation (`/api/v1/chat`), evaluation metrics execution (`/api/v1/evaluations`), and guardrails enforcement (`/api/v1/guardrails`).
- **Evaluation Engine**: Integrates Ragas and DeepEval frameworks to benchmark Faithfulness, Answer Relevance, Context Precision, and Context Recall against golden datasets.

---

## 4. Shared Data Contracts & Vector Schema

### 4.1 MinIO Object Namespace Structure
- **Direct Workspace Bucket**: `rag-raw-documents`
- **Per-Source Isolated Buckets**: `source-{source_name}-{source_id}`

### 4.2 Qdrant Vector Payload Schema
All vectors written to Qdrant follow a standardized metadata contract:
```json
{
  "document_id": "uuid-string",
  "file_name": "annual_report_2026.pdf",
  "source_id": "a8541818-bb30-44b5-8956-75e0e5ca7d88",
  "source_type": "google_drive",
  "bucket": "source-engineering-knowledge-a8541818",
  "pipeline_id": "p-9902-vector-index",
  "chunk_index": 14,
  "total_chunks": 85,
  "chunk_text": "The Q3 financial summary indicates a 24% growth in ARR...",
  "embedding_model": "text-embedding-3-small",
  "created_at": "2026-08-30T10:15:30Z"
}
```

---

## 5. Environment Setup & Deployment Guide

### 5.1 System Prerequisites
- **Operating System**: Linux (Ubuntu 22.04+), macOS (Apple Silicon/Intel), or Windows 11 (WSL2 recommended)
- **Docker**: Docker Engine 24.0+ & Docker Compose v2.20+
- **Node.js**: Node v18.0+ or v20.0+ & npm 9+
- **Python**: Python 3.11+
- **Git**: Git 2.34+

### 5.2 Environment Variables Configuration

#### Root / Shared Docker Services (`.env` in `web-scrapper-workspace/`)
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

OPENAI_API_KEY=sk-proj-your-openai-key-here
```

#### Ingestion Backend (`ingestion-workspace/ingestion-backend/.env`)
```ini
PORT=8007
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rag_platform
REDIS_URL=redis://localhost:6379/0
MINIO_ENDPOINT=http://localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
QDRANT_HOST=localhost
QDRANT_PORT=6333
RAG_API_URL=http://localhost:8001
SCRAPER_API_URL=http://localhost:8000
```

#### Ingestion Frontend (`ingestion-workspace/ingestion-frontend/.env`)
```ini
VITE_API_BASE_URL=http://localhost:8007
VITE_RAG_API_URL=http://localhost:8001
VITE_SCRAPER_API_URL=http://localhost:8000
```

---

## 6. Step-by-Step Installation & Execution

### Step 1: Clone Repository
```bash
git clone https://github.com/your-org/new-multi-rag.git
cd new-multi-rag
```

### Step 2: Launch Shared Infrastructure (Postgres, Redis, MinIO, Qdrant)
```bash
cd web-scrapper-workspace
docker-compose up -d --build
```
*Verify container status:*
```bash
docker-compose ps
```

### Step 3: Run Database Migrations
```bash
cd ../ingestion-workspace/ingestion-backend
python -m venv venv
# Linux/macOS:
source venv/bin/activate
# Windows:
.\venv\Scripts\activate

pip install -r requirements.txt
alembic upgrade head
```

### Step 4: Start Ingestion Backend API & Celery Worker
```bash
# Terminal 1 - API Service (Port 8007)
python -m apps.api.main

# Terminal 2 - Celery Background Worker
celery -A apps.worker.main worker --loglevel=info
```

### Step 5: Start RAG Query API Service
```bash
cd ../../rag-app-workspace
python -m venv venv
source venv/bin/activate # or .\venv\Scripts\activate
pip install -r requirements.txt
python -m apps.api.main # Runs on Port 8001
```

### Step 6: Start Ingestion Frontend Dev Server
```bash
cd ../ingestion-workspace/ingestion-frontend
npm install
npm run dev
```
*Access the Web UI in your browser at:* `http://localhost:5173`

---

## 7. Operational Verification Checklist
1. **Frontend UI**: Open `http://localhost:5173` and verify Overview dashboard renders.
2. **Ingestion Backend API**: Open `http://localhost:8007/docs` and execute `GET /health`.
3. **RAG Query API**: Open `http://localhost:8001/docs` and execute `GET /health`.
4. **Scraper API**: Open `http://localhost:8000/docs` and execute `GET /health`.
5. **MinIO Console**: Open `http://localhost:9001` (Credentials: `minioadmin` / `minioadmin`).
6. **Qdrant Dashboard**: Open `http://localhost:6333/dashboard`.

---

## 8. Documentation Index

The `vijay-docs/` folder contains detailed technical implementations for every individual page in the system:

- [`01_overview_dashboard_page.md`](./01_overview_dashboard_page.md): System Metrics Overview & Activity Dashboard
- [`02_folders_and_file_browser_page.md`](./02_folders_and_file_browser_page.md): Folders, Directory Hierarchy & File Viewer
- [`03_data_sources_page.md`](./03_data_sources_page.md): Data Sources Management, Connectors Catalogue & Configuration
- [`04_document_upload_page.md`](./04_document_upload_page.md): Document Upload & Multi-Format Ingestion Engine
- [`05_rag_pipelines_page.md`](./05_rag_pipelines_page.md): RAG Pipelines, Chunking Strategies & Vector Indexing
- [`06_rag_chat_page.md`](./06_rag_chat_page.md): RAG Chat Assistant, Hybrid Search & Reranking Playground
- [`07_prompts_management_page.md`](./07_prompts_management_page.md): System Prompts Management & Version Control
- [`08_realtime_monitoring_page.md`](./08_realtime_monitoring_page.md): Real-Time System Metrics & Performance Dashboard
- [`09_offline_evaluation_page.md`](./09_offline_evaluation_page.md): Offline Evaluation & Golden Dataset Benchmarking
- [`10_tracking_and_traces_page.md`](./10_tracking_and_traces_page.md): OpenTelemetry Tracing & Observability
- [`11_ai_guardrails_page.md`](./11_ai_guardrails_page.md): AI Guardrails Configuration, Tracing & Moderation
