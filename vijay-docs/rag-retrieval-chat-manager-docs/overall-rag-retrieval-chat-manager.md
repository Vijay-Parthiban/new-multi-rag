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

## 2. Navigation Structure (11 Pages)

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                             RAG RETRIEVAL CHAT MANAGER UI (5174)                            │
├───────────────────────┬─────────────────────────────────────────────────────────────────────┤
│ Sidebar Link          │ Route Path & Description                                            │
├───────────────────────┼─────────────────────────────────────────────────────────────────────┤
│ 1. Overview           │ /                  - Retrieval system stats & query volume summary  │
│ 2. Pipelines          │ /pipelines         - RAG pipeline strategies & Qdrant collections   │
│ 3. Chat               │ /chat              - Interactive RAG query testing & citation view│
│ 4. Prompts            │ /prompts           - System prompt engineering & template playground│
│ 5. Realtime Monitoring│ /monitoring        - Sub-second latency breakdown & trace telemetry │
│ 6. Offline Evaluation │ /evaluation        - Benchmark test datasets & Ragas evaluation runs│
│ 7. Tracking & Traces  │ /tracking          - OpenTelemetry execution traces & token cost    │
│ 8. Guard Config       │ /guard-config      - AI Guardrails moderation policy rules        │
│ 9. Guard Traces       │ /guard-traces      - Safety inspection logs & policy violations  │
│ 10. Guard Evaluation  │ /guard-eval        - Automated red-teaming & guardrail safety metrics│
│ 11. Knowledge Store   │ /knowledge-store   - Read-only proxy view of Ingestion profiles   │
└───────────────────────┴─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Core Technical Architecture & RAG Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   HYBRID RETRIEVAL PIPELINE                                 │
├─────────────────────────────────────────────────────────────────────────────────────────────┤
│ 1. User Query -> Input Guardrails Moderation Check (Port 8002)                              │
│ 2. Hybrid Retrieval Execution (Port 8001):                                                  │
│    - Dense Search: Qdrant Vector DB (SentenceTransformers / OpenAI embeddings)              │
│    - Sparse Search: BM25 FastEmbed text index                                               │
│ 3. Reciprocal Rank Fusion (RRF) & Cross-Encoder Reranking                                   │
│ 4. Prompt Template Injection (Port 8001 System Prompts)                                     │
│ 5. LLM Answer Synthesis (OpenAI / Ollama / Local VLLM)                                      │
│ 6. Output Guardrails Check & Hallucination Filter (Port 8002)                               │
│ 7. OpenTelemetry Trace Generation & UI Streaming (Port 5174)                                │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Backend API Routes Reference

### 4.1. RAG Query Backend (`http://localhost:8001`)
| Method | Endpoint Path | Description |
| :--- | :--- | :--- |
| `GET` | `/health` | RAG API service health check |
| `GET` | `/api/rag/pipelines` | List configured RAG pipelines & collections |
| `POST` | `/api/rag/pipelines` | Create a new pipeline strategy |
| `GET` | `/api/rag/pipelines/options` | Fetch strategy & model options |
| `POST` | `/api/rag/chat` | Execute hybrid RAG query with stream/citation output |
| `GET` | `/api/rag/chat/sessions` | Fetch active chat session history |
| `GET` | `/api/rag/prompts` | List prompt templates |
| `POST` | `/api/rag/prompts` | Save prompt template |
| `GET` | `/api/rag/evaluations/datasets` | List benchmark test datasets |
| `POST` | `/api/rag/evaluations/runs` | Execute offline evaluation run |

### 4.2. Guardrails Moderation Service (`http://localhost:8002`)
| Method | Endpoint Path | Description |
| :--- | :--- | :--- |
| `GET` | `/api/guardrails/config` | Fetch active safety moderation rules |
| `POST` | `/api/guardrails/config` | Update guardrail policies & threshold sliders |
| `GET` | `/api/guardrails/traces` | Fetch moderation execution traces |
| `POST` | `/api/guardrails/evaluate` | Trigger automated red-teaming evaluation run |

---

## 5. How to Run `rag-retrieval-chat-manager` in a New Environment

### 5.1. Start Infrastructure & Backends
```bash
# 1. Start Qdrant, Postgres, Redis
cd new-multi-rag/ingestion-workspace
docker-compose up -d postgres qdrant redis

# 2. Start RAG Query API (Port 8001)
cd ../rag-app-workspace/apps/rag-query-api
source .venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8001 --reload

# 3. Start Guardrails Service (Port 8002)
cd ../../../guardrails-service
uvicorn main:app --host 0.0.0.0 --port 8002 --reload
```

### 5.2. Start Retrieval & Chat Manager Frontend
```bash
cd rag-retrieval-chat-manager/frontend
npm install
npm run dev
# App will open at http://localhost:5174
```
