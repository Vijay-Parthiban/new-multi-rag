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
│  Main Navigation (4 Tabs + Subpages): │                     │  Main Navigation (11 Items):             │
│   1. Overview (/)                      │                     │   1. Overview (/)                        │
│   2. Folders (/browse)                 │                     │   2. Knowledge Store (/knowledge-store)  │
│   3. Sources (/sources)                │                     │   3. Pipelines (/pipelines)              │
│   4. Knowledge Store (/knowledge-store)│                     │   4. Chat (/chat)                        │
│   + Upload (/upload)                   │                     │   5. Prompts (/prompts)                  │
│   + Source Detail (/sources/:id)       │                     │   6. Real Time Monitoring (/evaluations) │
│                                        │                     │   7. Offline Evaluation (/golden-evals)  │
│                                        │                     │   8. Tracking (/tracking)                │
│                                        │                     │   9. Guard Config (/guardrails-config)   │
│                                        │                     │   10. Guard Traces (/guardrails-traces)  │
│                                        │                     │   11. Guard Eval (/guardrails-eval)      │
└────────────────────────────────────────┘                     └──────────────────────────────────────────┘
```

---

## 2. Core Operational Capabilities & Polling Synchronizations

### 2.1. Ingestion Manager (`rag-ingestion-manager`)
- **MinIO Dedicated Source Buckets**: Every source maps to a dedicated MinIO S3 bucket (`source-<name>-<hash>`) or local filesystem directory (`storage/local_sources/<folder>`).
- **Automatic Live & Scheduled Background Polling**:
  - **Live Mode**: Instantaneous continuous background polling loop (3-second sleep interval for <5s sync latency).
  - **Scheduled Mode**: Precise background polling loop running every `connector_sync_interval_minutes` or connector `sync_interval_minutes`.
  - **Automatic Initialization**: Background pollers start automatically on server startup via `init_all_source_pollers()` called within FastAPI `lifespan` in `apps/api/main.py`.
  - **Dynamic Task Lifecycle**: Pollers register dynamically (`register_source_poller`) on source creation, update, or connector modification, trigger an immediate initial background sync (`_trigger_initial_sync`), and stop cleanly (`stop_source_poller`) on source deletion.
  - **Manual Sync**: Manual "Sync Now" trigger remains available as an optional manual action alongside continuous polling.
- **Universal Multi-Sink Fanout Engine**: Distributes ingested source documents across 5 enterprise destination types (Qdrant, OpenSearch, Neo4j, PostgreSQL, RedisVL) via Knowledge Profiles.
- **Resumable 5MB Chunked Uploads**: Client-side SHA256 hashing and sequential/parallel 5MB chunk streaming with server-side MinIO object assembly.

### 2.2. Retrieval & Chat Manager (`rag-retrieval-chat-manager`)
- **Hybrid Retrieval Engine**: Combines dense vector similarity (Qdrant) with sparse lexical search (BM25 FastEmbed) and Cross-Encoder reranking.
- **RAG Strategy Catalog**: Naive, HyDE, Multi-Query Fusion, Parent-Child Chunking, and GraphRAG.
- **System Prompt Registry**: Dynamic live template overrides and packaged fallbacks across `generation_core` and `rag_core`.
- **AI Guardrails Moderation Engine (Port 8002)**: Input/output toxicity checking, PII redaction, prompt injection defense, hallucination detection, and red-teaming evaluations.
- **Comprehensive Monitoring & Tracing**: Real-time sub-second latency waterfall, token usage tracking, and benchmark evaluation execution using Ragas/DeepEval metrics.

---

## 3. System Architecture Mapping

### 3.1. Infrastructure Services
- **PostgreSQL**: Stores sources, connectors, directories, files, sync jobs, knowledge profiles, pipelines, chat sessions, traces, and guardrail rules.
- **MinIO S3**: Manages document buckets (`source-*`, `local-*`) and raw file chunks (`uploads/`).
- **Qdrant Vector Database**: Stores dense vector embeddings and BM25 sparse payloads across collections.
- **Redis**: Coordinates RQ evaluation worker queues and RedisVL semantic caches.

---

## 4. Documentation Index

The complete documentation suite in `vijay-docs/` is split into two specialized subfolders:
1. `rag-ingestion-manager-docs/`: 5 detailed page specifications covering document ingestion, folders, data sources & automatic background polling, knowledge profiles, and chunked uploads.
2. `rag-retrieval-chat-manager-docs/`: 11 detailed page specifications covering overview, pipelines, chat, prompts, real-time monitoring, offline evaluations, tracking traces, AI guardrails configuration, guardrails traces, guardrails red-teaming evaluation, and knowledge store proxy.
