# rag-retrieval-chat-manager — Detailed System Documentation

## 1. Executive Summary & Application Scope

The **`rag-retrieval-chat-manager`** is a dedicated full-stack management application focused on hybrid vector retrieval, interactive RAG chat testing, prompt template engineering, real-time performance trace monitoring, Ragas/DeepEval offline evaluation execution, AI guardrails safety moderation, and proxy viewing of knowledge store resources.

- **Frontend UI Port**: `5174` (`http://localhost:5174`)
- **RAG Query API Port**: `8001` (`http://localhost:8001`)
- **Guardrails Service Port**: `8002` (`http://localhost:8002`)
- **Vite Proxy Rules**:
  - `/api/rag` -> `http://localhost:8001`
  - `/api/evaluations` -> `http://localhost:8001`
  - `/api/prompts` -> `http://localhost:8001`
  - `/api/guardrails` -> `http://localhost:8002`
  - `/api` -> `http://localhost:8007` (Knowledge Store read-only proxy)

---

## 2. Navigation Structure (11 Items)

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                             RAG RETRIEVAL CHAT MANAGER UI (5174)                            │
├───────────────────────┬─────────────────────────────────────────────────────────────────────┤
│ Sidebar Link          │ Route Path & Description                                            │
├───────────────────────┼─────────────────────────────────────────────────────────────────────┤
│ 1. Overview           │ /                      - Retrieval system stats & query volume      │
│ 2. Knowledge Store    │ /knowledge-store       - Read-only proxy view of Knowledge Profiles │
│ 3. Pipelines          │ /pipelines             - RAG pipeline strategies & Qdrant mappings  │
│ 4. Chat               │ /chat                  - Interactive RAG query testing & citations  │
│ 5. Prompts            │ /prompts               - System prompt template engineering         │
│ 6. Real Time Monitoring│ /evaluations           - Sub-second latency breakdown & telemetry    │
│ 7. Offline Evaluation │ /golden-evaluations    - Benchmark test sets & offline eval runs    │
│ 8. Tracking           │ /tracking              - OpenTelemetry execution traces & token cost │
│ 9. Guardrails Config  │ /guardrails-config     - AI Guardrails moderation policy rules      │
│ 10. Guardrails Traces │ /guardrails-traces     - Safety inspection logs & policy violations  │
│ 11. Guardrails Eval   │ /guardrails-evaluation - Automated red-teaming & guardrail metrics  │
└───────────────────────┴─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Core Technical Architecture & Hybrid Retrieval Engine

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   HYBRID RETRIEVAL PIPELINE                                 │
├─────────────────────────────────────────────────────────────────────────────────────────────┤
│ 1. User Query -> Input Guardrails Moderation Check (Port 8002)                              │
│ 2. Hybrid Retrieval Execution (Port 8001):                                                  │
│    - Dense Search: Qdrant Vector DB (SentenceTransformers / OpenAI embeddings)              │
│    - Sparse Search: BM25 FastEmbed text index                                               │
│    - Reciprocal Rank Fusion (RRF) & Cross-Encoder Reranking                                 │
│ 3. Prompt Template Assembly (`generation_core` & `rag_core` overrides)                      │
│ 4. LLM Generation & Output Guardrails Verification                                          │
│ 5. Response Streaming with Source Citations & Telemetry Tracing                             │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. API Routes Overview

- **RAG & Search API (Port 8001)**: `/api/rag/chat`, `/api/rag/pipelines`, `/api/rag/prompts`, `/api/rag/evaluations`, `/api/rag/traces`.
- **Guardrails API (Port 8002)**: `/api/guardrails/config`, `/api/guardrails/traces`, `/api/guardrails/evaluate`.
- **Ingestion Proxy Path (Port 8007)**: `/api/knowledge-profiles` -> Proxying calls to Ingestion Manager backend.
