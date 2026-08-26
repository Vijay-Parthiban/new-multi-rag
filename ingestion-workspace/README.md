# Multi-RAG Ingestion Platform & Stream Processing Pipeline

Comprehensive document upload, Airbyte connector stream ingestion, and file management platform powered by Pathway CDC, FastAPI, React, MinIO object storage, and Qdrant vector database.

> 📘 **Full Architecture & Environment Replication Guide**: See [`PROJECT_IMPLEMENTATION_AND_STATE.md`](../PROJECT_IMPLEMENTATION_AND_STATE.md) for complete step-by-step instructions on replicating and running the project in any environment.


## 1. Quick Start

```bash
# Clone repository and navigate to workspace
git clone https://github.com/Vijay-Parthiban/new-multi-rag.git
cd new-multi-rag/ingestion-workspace

# Start all 12 Docker containers
docker compose up -d

# Start the frontend dev server
cd ingestion-frontend
npm install
npm run dev
```

### Microservice Endpoints & Services

| Service | Internal Port | External Host Port | Public / Local URL |
| :--- | :--- | :--- | :--- |
| **Frontend UI (Vite + React)** | 5173 | **5173** | `http://localhost:5173` |
| **Ingestion Backend API** | 8000 | **8007** | `http://localhost:8007` |
| **RAG Query API** | 8001 | **8001** | `http://localhost:8001` |
| **Web Scraper API** | 8000 | **8000** | `http://localhost:8000` |
| **Qdrant Vector Database** | 6333 | **6333** | `http://localhost:6333/dashboard` |
| **MinIO Console & Storage** | 9000 / 9001 | **9000 / 9001** | `http://localhost:9001` (`minioadmin` / `minioadmin`) |
| **PostgreSQL Database** | 5432 | **5433** | `localhost:5433` (`ingestion` + `crawler` DBs) |
| **Redis Cache & Queue** | 6379 | **6379** | `localhost:6379` |
| **ngrok Tunnel Agent** | 4040 | **4040** | `http://localhost:4040` |


## 2. Core Architecture Highlights

- **Differential State CRUD Sync Engine (`gdrive_sync.py` & `pathway_sync.py`)**: Real-time Change Data Capture (CDC) state reflection. File additions, updates/modifications, obsolete key cleanups, and deletions in external sources are automatically mirrored to MinIO storage.
- **Sub-5-Second Live Polling (< 3s latency)**: Continuous background pollers automatically initialized via FastAPI `lifespan` in `apps/api/main.py`.
- **Multi-Connector Storage Isolation**: S3-compatible MinIO object storage bucket per source with connector-isolated namespaces (`connectors/{connector_id}/...`).
- **Pathway CDC Engine (`pw.io.airbyte.read`)**: Stream processing from 12+ Airbyte connectors with dynamic tuple retractions (`+1` additions, `-1/+1` updates, `-1` retractions).
- **Flat & Tree File Browser Views**: React frontend `FileBrowser.tsx` featuring instant switching between flat file views and directory tree structure.


## 3. Key Components & Implementation Files

- `src/ingestion_service/core/gdrive_sync.py`: Google Drive differential sync engine (ADD, UPDATE, OBSOLETE CLEANUP, DELETE).
- `src/ingestion_service/core/pathway_sync.py`: Pathway background pollers, concurrency guards, and lifespan initialization.
- `apps/api/main.py`: FastAPI server entrypoint & lifespan poller startup hook.
- `src/shared/config/settings.py` & `src/shared/storage/s3_client.py`: System configuration & async MinIO S3 client.
- `ingestion-frontend/src/pages/SourceDetailPage.tsx`: Source details, connector catalogue, and MinIO bucket file management UI.
