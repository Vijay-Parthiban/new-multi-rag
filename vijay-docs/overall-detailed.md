# Universal Multi-RAG Platform — Master Architecture & Operational Guide

## 1. Executive Summary & Platform Overview

The **Universal Multi-RAG Ecosystem** (`new-multi-rag`) is an enterprise-grade, microservices-based Retrieval-Augmented Generation (RAG) platform. The codebase is organized into two domain-isolated sub-projects operating on shared underlying storage and vector infrastructure:

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
│  Vite Proxy: /api -> 127.0.0.1:8007    │                     │  Guardrails API: http://localhost:8002   │
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
│                                        │                     │  11. Knowledge Store (/knowledge-store)  │
└────────────────────────────────────────┘                     └──────────────────────────────────────────┘
```

---

## 2. Platform Architecture & Data Flow

### 2.1. Ingestion Pipeline & Storage Layer (`rag-ingestion-manager`)
1. **Source Connectors**: Connects to Google Drive, S3, Azure Blob, Google Sheets, SQL DBs, Web Scrapers, or Local Filesystem.
2. **Sync Engine (`gdrive_sync.py` & `pathway_sync.py`)**: Runs connector downloads in `asyncio.to_thread` and uploads files directly into dedicated MinIO S3 buckets (`source-<name>-<hash>`).
3. **Threaded MinIO S3 Client (`s3_client.py`)**: Executes all S3 operations using synchronous `boto3` inside `asyncio.to_thread` for non-blocking execution and event loop stability under Windows asyncio. Automatically calculates `total_files` and `total_size_bytes` per source.
4. **Universal Multi-Sink Fanout Engine (`universal_fanout.py`)**: Processes documents into 5 destination sinks:
   - **Qdrant**: Vector embeddings & BM25 sparse vectors.
   - **OpenSearch**: Lexical BM25 & SPLADE indices.
   - **Neo4j**: GraphRAG entity-relation summaries & graph triplets.
   - **PostgreSQL**: `pgvector` / `pgvectorscale` tables.
   - **RedisVL**: Semantic summary maps & RAPTOR trees.

### 2.2. Retrieval, Chat & Monitoring Layer (`rag-retrieval-chat-manager`)
1. **Hybrid Vector Search**: Combines Qdrant dense vector search with OpenSearch BM25 sparse keyword search using Reciprocal Rank Fusion (RRF).
2. **Cross-Encoder Reranking**: Re-ranks top candidate chunks to surface relevant context.
3. **RAG Chat & Citation Engine**: Synthesizes answers using customizable prompt templates and streams responses with inline source citations.
4. **AI Guardrails Moderation**: Filters input queries and output responses using NeMo / LlamaGuard safety policies.
5. **Telemetry & Offline Evaluation**: Tracks request traces, token usage, latency distribution, and RAGAS offline evaluation metrics.

---

## 3. Port & Service Summary

| Service | Host Port | Protocol / Proxy | Purpose |
|---|---|---|---|
| Ingestion Manager Frontend | `5173` | HTTP / React (Vite) | Ingestion Dashboard, Sources, Folders, Knowledge Store, Upload UI |
| Ingestion Manager API | `8007` | FastHTTP / FastAPI | Sources, Connectors, MinIO S3 Storage, Directories, Fanout Engine |
| Retrieval Chat Frontend | `5174` | HTTP / React (Vite) | Chat UI, Pipelines, Prompts, Monitoring, Traces, Guardrails UI |
| Retrieval Chat API | `8001` | FastAPI / Python | RAG Querying, Hybrid Search, Chat Sessions, Prompts, RAGAS Eval |
| Guardrails API | `8002` | FastAPI / Python | Safety Moderation, PII Detection, Guardrails Traces & Evaluation |
| MinIO S3 Console & API | `9000` / `9001` | S3 API / HTTP | Physical object storage buckets for document sources |
| Qdrant Vector DB | `6333` / `6334` | HTTP / gRPC | High-performance vector embeddings & payload storage |
| PostgreSQL DB | `5432` | PostgreSQL Protocol | Metadata persistence, pipeline sync queue, chat sessions, trace logs |
| Redis Cache | `6379` | Redis Protocol | Async task queue, semantic cache, RAPTOR trees |
