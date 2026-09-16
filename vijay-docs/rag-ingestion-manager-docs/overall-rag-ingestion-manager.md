# Overall Architecture — RAG Ingestion Manager

## 1. System Overview
`rag-ingestion-manager` is the enterprise document ingestion, storage management, parsing, and multi-sink synchronization engine of the `new-multi-rag` platform. It bridges unstructured documents residing in external systems (Google Drive, S3, Azure, SFTP, Web Scrapers, MinIO) into a unified MinIO object store and orchestrates parallel fanout into **5 enterprise RAG storage destinations**: **Qdrant Vector DB**, **OpenSearch BM25**, **Neo4j Knowledge Graph**, **PostgreSQL Relational Chunks**, and **RedisVL Semantic Cache**.

---

## 2. Full Architecture Topology

```
+---------------------------------------------------------------------------------------------------+
|                                  DATA INGESTION PERIMETER                                         |
|  [ MinIO Buckets ] [ Manual Uploads ] [ Google Drive ] [ S3 / Azure ] [ SFTP ] [ Web Scrapers ]   |
+-------------------------------------------------+-------------------------------------------------+
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
|                                 RAG INGESTION MANAGER BACKEND                                     |
|  +---------------------------+  +-------------------------------+  +---------------------------+  |
|  | Fast-API REST Gateway     |  | Background Sync Runners       |  | Document Processing Core  |  |
|  | - /api/sources            |  | - sync_runner.py              |  | - pypdf / python-docx     |  |
|  | - /api/directories        |  | - pathway_sync.py             |  | - recursive text chunker  |  |
|  | - /api/knowledge-profiles |  | - airbyte_connector.py        |  | - SHA256 deduplication    |  |
|  | - /api/uploads            |  | - gdrive_sync.py              |  | - Embedding Client (384D) |  |
|  +---------------------------+  +-------------------------------+  +---------------------------+  |
+-------------------------------------------------+-------------------------------------------------+
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
|                              UNIVERSAL 5-SINK FANOUT ENGINE                                       |
|                                  (universal_fanout.py)                                            |
|  Executes concurrent, idempotent writes to all 5 storage layers per Knowledge Routing Profile:    |
|                                                                                                   |
|  +--------------------+  +--------------------+  +--------------------+  +--------------------+   |
|  | 🔮 Qdrant Vector   |  | 🔍 OpenSearch BM25 |  | 🕸️ Neo4j Graph     |  | 🐘 PostgreSQL Chunks|   |
|  | - Dense Embeddings |  | - Inverted Index   |  | - Entity Extraction|  | - Relational Chunk  |   |
|  | - HNSW Index       |  | - Keyword Scoring  |  | - Doc-Chunk Graph  |  |   Persistence       |   |
|  +--------------------+  +--------------------+  +--------------------+  +--------------------+   |
|                                 +--------------------+                                            |
|                                 | ⚡ RedisVL Cache   |                                            |
|                                 | - Semantic Query   |                                            |
|                                 |   Deduplication    |                                            |
|                                 +--------------------+                                            |
+-------------------------------------------------+-------------------------------------------------+
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
|                                RAG INGESTION MANAGER FRONTEND                                     |
|  +--------------------+  +--------------------+  +--------------------+  +--------------------+   |
|  | Ingestion Overview |  | Folders & Files    |  | Data Sources       |  | Knowledge Store    |   |
|  | Dashboard          |  | Browser & Viewer   |  | Manager            |  | Fanout Visualizer  |   |
|  +--------------------+  +--------------------+  +--------------------+  +--------------------+   |
+---------------------------------------------------------------------------------------------------+
```

---

## 3. Directory & Codebase Structure
```
rag-ingestion-manager/
├── backend/
│   ├── apps/
│   │   ├── api/
│   │   │   ├── routes/
│   │   │   │   ├── sources.py          # Data source CRUD, testing, and sync triggers
│   │   │   │   ├── knowledge.py        # Knowledge profile CRUD, fanout sync, and 5-sink inspect APIs
│   │   │   │   ├── directories.py      # Virtual workspace directory management
│   │   │   │   ├── files.py            # File metadata and chunk operations
│   │   │   │   └── uploads.py          # Multipart browser file upload handler
│   │   │   └── main.py                 # FastAPI application assembly and CORS middleware
│   │   ├── pathway_worker/             # Real-time streaming synchronization worker
│   │   └── worker/                     # Scheduled background worker for periodic connector polling
│   └── src/
│       ├── ingestion_service/
│       │   ├── core/
│       │   │   ├── universal_fanout.py # 5-destination fanout sync engine
│       │   │   ├── sync_runner.py      # Source-to-staging synchronization worker
│       │   │   ├── pathway_sync.py     # Streaming connector manager
│       │   │   ├── gdrive_sync.py      # Google Drive OAuth / service account connector
│       │   │   ├── airbyte_connector.py# Airbyte integration client
│       │   │   └── indexer.py          # Text extraction and vector embedding generator
│       │   ├── embeddings/
│       │   │   ├── client.py           # Dense embedding client (HuggingFace / Ollama / OpenAI)
│       │   │   └── sparse_client.py    # BM25 / SPLADE sparse vector client
│       │   └── vector/
│       │       └── qdrant_store.py     # Qdrant client wrapper and collection management
│       └── shared/
│           ├── db/
│           │   └── models.py           # SQLAlchemy models: Source, KnowledgeProfile, Directory, File
│           └── storage/
│               └── s3_client.py        # MinIO S3 client wrapper
└── frontend/
    └── src/
        ├── api.ts                      # Typed API client for all backend endpoints
        ├── pages/
        │   ├── HomePage.tsx            # Overview dashboard with metrics & quick actions
        │   ├── BrowsePage.tsx          # Folders & file explorer with document preview
        │   ├── SourcesPage.tsx         # Connector management and MinIO bucket configuration
        │   ├── SourceDetailPage.tsx    # Detailed file list & sync logs for individual source
        │   ├── KnowledgeStorePage.tsx  # Knowledge profile manager & visualizer trigger hub
        │   └── DirectoryPage.tsx       # Folder workspace browser
        └── components/
            └── visualizers/            # 5 interactive live inspection visualizers
                ├── DestinationVisualizerModal.tsx # Tabbed visualizer modal wrapper
                ├── VectorVisualizer.tsx           # 2D PCA vector cluster visualizer
                ├── LexicalVisualizer.tsx          # OpenSearch term frequency & BM25 explorer
                ├── GraphVisualizer.tsx            # Neo4j force-directed entity graph
                ├── RelationalVisualizer.tsx       # PostgreSQL chunk tabular inspector
                └── CacheVisualizer.tsx            # RedisVL semantic cache metrics & key explorer
```

---

## 4. Key Engineering Invariants
1. **Idempotent Ingestion**: File deduplication via SHA-256 prevents redundant chunking and embedding operations across repeated sync cycles.
2. **Decoupled 5-Sink Fanout**: A sync failure in one non-critical sink does not abort writes to the other 4 destinations; errors are captured per sink in `KnowledgeProfile.last_sync_error`.
3. **Live Inspectability**: All 5 destination stores expose live read-back APIs (`/api/knowledge-profiles/{id}/inspect/{destination_type}`) powering zero-latency visual validation directly inside the UI.
