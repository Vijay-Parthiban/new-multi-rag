# Universal Multi-RAG Platform — Master Architecture & Operational Guide

## 1. Executive Summary & Platform Overview

The **Universal Multi-RAG Ecosystem** (`new-multi-rag`) is an enterprise-grade, microservices-based Retrieval-Augmented Generation (RAG) platform. The codebase is organized into two completely domain-isolated sub-projects operating on shared underlying storage and vector infrastructure:

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                       SHARED INFRASTRUCTURE LAYER                                       │
│    PostgreSQL (5432)   │   Redis (6379)   │   MinIO S3 (9000/9001)   │   Qdrant Vector DB (6333/6334)   │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                    ▲
                                                    │
             ┌──────────────────────────────────────┴──────────────────────────────────────┐
             │                                                                             │
┌────────────────────────────────────────┐                     ┌──────────────────────────────────────────┐
│         rag-ingestion-manager          │                     │       rag-retrieval-chat-manager         │
│                                        │                     │                                          │
│  UI: http://localhost:5173             │                     │  UI: http://localhost:5174               │
│  API: http://localhost:8007            │                     │  API: http://localhost:8001              │
│  Vite Proxy: /api -> 8007              │                     │  Guardrails API: http://localhost:8002   │
│                                        │                     │  Vite Proxy: /api -> 8007, /api/rag -> 8001│
│  Scope: Document Ingestion & Storage   │                     │  Scope: Retrieval, Chat, Monitoring, Eval│
│  Pages (5):                            │                     │  Pages (11):                             │
│   1. Overview (/)                      │                     │   1. Overview (/)                        │
│   2. Folders (/browse)                 │                     │   2. RAG Pipelines (/pipelines)          │
│   3. Data Sources (/sources)           │                     │   3. RAG Chat (/chat)                    │
│   4. Knowledge Store (/knowledge-store)│                     │   4. Prompts (/prompts)                  │
│   5. Upload (/upload)                  │                     │   5. Realtime Monitoring (/monitoring)   │
│                                        │                     │   6. Offline Evaluation (/evaluation)    │
│                                        │                     │   7. Tracking & Traces (/tracking)       │
│                                        │                     │   8. Guard Config (/guard-config)        │
│                                        │                     │   9. Guard Traces (/guard-traces)        │
│                                        │                     │  10. Guard Evaluation (/guard-eval)     │
│                                        │                     │  11. Knowledge Store Proxy (/knowledge-store)│
└────────────────────────────────────────┘                     └──────────────────────────────────────────┘
```

---

## 2. Infrastructure & Shared Services Map

| Service Name | Default Port | Internal / Host Binding | Purpose / Description |
| :--- | :--- | :--- | :--- |
| **Ingestion Frontend** | `5173` | `http://localhost:5173` | `rag-ingestion-manager` UI (5 Pages) |
| **Retrieval/Chat Frontend** | `5174` | `http://localhost:5174` | `rag-retrieval-chat-manager` UI (11 Pages) |
| **Ingestion API** | `8007` | `http://localhost:8007` | Data ingestion, source connectors, file upload, directories, knowledge store |
| **RAG Query API** | `8001` | `http://localhost:8001` | RAG hybrid retrieval, chat synthesis, prompt management, offline evaluation |
| **Guardrails API** | `8002` | `http://localhost:8002` | Input/Output moderation, toxicity filtering, PII masking, hallucination check |
| **Scraper API** | `8000` | `http://localhost:8000` | Web scraper and deep-crawler service |
| **PostgreSQL** | `5432` | `localhost:5432` | Primary relational database (`rag_db`, `user: postgres`, `password: postgres`) |
| **Redis** | `6379` | `localhost:6379` | Celery task queue & caching broker |
| **MinIO S3** | `9000` (API) / `9001` (UI) | `http://localhost:9000` | Blob storage (`access_key: minioadmin`, `secret_key: minioadmin`) |
| **Qdrant Vector DB** | `6333` (HTTP) / `6334` (gRPC)| `http://localhost:6333` | Dense & sparse vector index engine |

---

## 3. Shared Libraries & Workspace Modules

- **`shared-libs/platform-common`**: Python core library containing embedding wrappers (dense SentenceTransformers/OpenAI, sparse BM25 FastEmbed), MinIO S3 clients, Qdrant database clients, authentication, and SSRF prevention utilities.
- **`rag-app-workspace/libs/shared`**: Shared RAG telemetry, OpenTelemetry tracing decorators (`@trace_span`), logger formatters, and custom exception handlers.

---

## 4. Step-by-Step Guide: Running in a New Environment

### Step 4.1. System Prerequisites
Ensure the following tools are installed on the host operating system:
- **Python**: `3.11` or `3.12`
- **Node.js**: `v18.0.0+` or `v20.0.0+` (or **Bun** `v1.0+`)
- **Docker & Docker Compose**: (For launching Postgres, Redis, MinIO, Qdrant)

---

### Step 4.2. Environment Configuration File (`.env`)
Create a root `.env` file or export the following variables in your terminal:

```env
# Database & Cache
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=rag_db
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/rag_db
REDIS_URL=redis://localhost:6379/0

# Object Storage (MinIO)
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_SECURE=false

# Vector Database (Qdrant)
QDRANT_HOST=localhost
QDRANT_PORT=6333

# Service Ports & APIs
INGESTION_API_PORT=8007
RAG_API_PORT=8001
GUARDRAILS_API_PORT=8002
SCRAPER_API_PORT=8000

# Frontend Proxies
VITE_API_URL=http://localhost:8007
VITE_RAG_API_URL=http://localhost:8001
VITE_GUARDRAILS_API_URL=http://localhost:8002
```

---

### Step 4.3. Launch Infrastructure (Docker Compose)
Launch the shared storage services:

```bash
# Navigate to the workspace root
cd new-multi-rag/ingestion-workspace

# Start Postgres, Redis, MinIO, Qdrant in detached mode
docker-compose up -d postgres redis minio qdrant
```

---

### Step 4.4. Backend Setup & Database Migrations

```bash
# 1. Create and activate a Python virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 2. Install shared platform packages
pip install -e shared-libs/platform-common
pip install -e rag-app-workspace/libs/shared

# 3. Install ingestion backend dependencies
cd ingestion-workspace/ingestion-backend
pip install -r requirements.txt

# 4. Run Alembic Database Migrations
alembic upgrade head
```

---

### Step 4.5. Starting Backend API Services

#### 1. Ingestion API Backend (Port 8007)
```bash
cd ingestion-workspace/ingestion-backend
uvicorn apps.api.main:app --host 0.0.0.0 --port 8007 --reload
```

#### 2. RAG Query API Backend (Port 8001)
```bash
cd rag-app-workspace/apps/rag-query-api
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

#### 3. AI Guardrails API Service (Port 8002)
```bash
cd guardrails-service
uvicorn main:app --host 0.0.0.0 --port 8002 --reload
```

---

### Step 4.6. Starting Frontend UI Management Applications

#### 1. Start `rag-ingestion-manager` UI (Port 5173)
```bash
cd rag-ingestion-manager/frontend
npm install
npm run dev
# App will open at http://localhost:5173
```

#### 2. Start `rag-retrieval-chat-manager` UI (Port 5174)
```bash
cd rag-retrieval-chat-manager/frontend
npm install
npm run dev
# App will open at http://localhost:5174
```

---

## 5. Verification Checklist

1. **Ingestion Health**: Visit `http://localhost:8007/health` -> Returns `{"status": "ok"}`.
2. **RAG Query Health**: Visit `http://localhost:8001/health` -> Returns `{"status": "ok"}`.
3. **Ingestion UI**: Visit `http://localhost:5173` -> Displays 5 sidebar navigation links (`Overview`, `Folders`, `Sources`, `Knowledge Store`, `Upload`).
4. **Retrieval & Chat UI**: Visit `http://localhost:5174` -> Displays 11 sidebar navigation links (`Pipelines`, `Chat`, `Prompts`, `Real Time Monitoring`, `Offline Evaluation`, `Tracking`, `Guard Config`, `Guard Traces`, `Guard Evaluation`, `Knowledge Store`, `Overview`).
5. **Data Sources Test**: Open `http://localhost:5173/sources` -> Loads data sources cleanly with zero network errors.
