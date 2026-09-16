# End-to-End Architecture & Operational Manual — new-multi-rag

## 1. System Architecture Overview
The **`new-multi-rag`** platform is an enterprise-grade, distributed Retrieval-Augmented Generation (RAG) system composed of two decoupled and complementary subsystems:

1. **`rag-ingestion-manager`** (Frontend: Port `5173`, Backend: Port `8007`):
   - Ingestion perimeter managing external connectors (MinIO, Google Drive, AWS S3, Azure Blob, SFTP, Web Scrapers, Confluence).
   - Document staging, SHA-256 deduplication, multi-format parsing (PDF, DOCX, TXT, JSON, MD, CSV), and recursive text chunking.
   - **Universal 5-Sink Fanout Engine** (`universal_fanout.py`) syncing documents into 5 storage layers: **Qdrant Vector DB**, **OpenSearch BM25**, **Neo4j Knowledge Graph**, **PostgreSQL Relational Chunks**, and **RedisVL Semantic Cache**.
   - **Interactive Live Multi-Sink Visualizers** providing real-time data inspection for all 5 destination storage backends.

2. **`rag-retrieval-chat-manager`** (Frontend: Port `5174`, Backend: Port `8000`):
   - Multi-stage retrieval and conversational intelligence gateway.
   - Hybrid dense/sparse retrieval combining Qdrant HNSW and OpenSearch BM25.
   - Cross-encoder reranking (Cohere v3.5, BGE reranker) via LiteLLM.
   - Context-grounded generation supporting streaming SSE, vision multimodal inputs, and dynamic prompt templating.
   - Comprehensive safety guardrails powered by Microsoft Presidio (PII/SPI masking, prompt injection defense, toxic language filtering).
   - Continuous observability, OpenTelemetry distributed tracing, and offline Ragas evaluation suites.

---

## 2. End-to-End Data & Execution Lifecycle

```
========================================================================================================================
                                             PHASE 1: DATA INGESTION & 5-SINK FANOUT
========================================================================================================================
[ External Sources / Buckets ]   --->   [ MinIO Object Store ]   --->   [ Ingestion Backend ]
(Google Drive, S3, Manual, SFTP)         (v-res, manual-vj)             - Extract & Parse (PDF/DOCX)
                                                                        - SHA-256 Deduplication
                                                                        - Recursive Text Chunking (500 tokens)
                                                                        - Dense 384D/2048D Embeddings
                                                                                    |
                                                                                    v
                                                                    [ Universal Fanout Engine ]
                                                                      (universal_fanout.py)
                                                                                    |
            +-----------------------+-----------------------+-----------------------+-----------------------+
            |                       |                       |                       |                       |
            v                       v                       v                       v                       v
    +---------------+       +---------------+       +---------------+       +---------------+       +---------------+
    | 1. Qdrant     |       | 2. OpenSearch |       | 3. Neo4j      |       | 4. PostgreSQL |       | 5. RedisVL    |
    | Vector DB     |       | BM25 Lexical  |       | Knowledge     |       | Relational    |       | Semantic      |
    | (Dense HNSW)  |       | (Inverted)    |       | Graph (Entity)|       | Chunks (Meta) |       | Cache (Sub-5ms|
    +---------------+       +---------------+       +---------------+       +---------------+       +---------------+

========================================================================================================================
                                           PHASE 2: RAG RETRIEVAL, SYNTHESIS & EVALUATION
========================================================================================================================
[ User / Chat Client ]
        |
        v
[ Input Guardrails Check ] (Presidio PII Masking, Prompt Injection, Banned Words)
        |  [Violation -> Intercept with BlockedCard]
        v  [Clean -> Proceed]
[ Hybrid Retrieval Engine ]
   |-- Qdrant Vector Search (Dense HNSW Top-20)
   |-- OpenSearch Lexical Search (BM25 Top-20)
   |-- Reciprocal Rank Fusion / Alpha-weighted scoring (0.7 Dense / 0.3 Sparse)
        |
        v
[ Cross-Encoder Reranker ] (Cohere v3.5 / BGE Reranker -> Top-5 Chunks)
        |
        v
[ Generation Engine (LiteLLM) ] (System Prompt + Cited Context + User Query -> GPT-4o / Claude 3.5 / Llama 3)
        |
        v
[ Output Guardrails & Redaction ] (Toxicity filter, PII scrubbing)
        |
        v
[ Streaming Token Delivery to User ] + [ OpenTelemetry Trace Log ] + [ Async Ragas Evaluation ]
```

---

## 3. Storage Layer Matrix & Port Allocations

| Service / Sink | Default Port | Internal Role & Data Payload |
|---|---|---|
| **RAG Ingestion Backend** | `8007` | FastAPI ingestion gateway, connector sync, fanout engine, sink inspection APIs |
| **RAG Ingestion Frontend** | `5173` | Vite/React dashboard, file browser, sources manager, 5-sink visualizer modals |
| **RAG Retrieval Backend** | `8000` | FastAPI chat, hybrid retrieval, reranking, generation, guardrails, eval APIs |
| **RAG Retrieval Frontend** | `5174` | Vite/React chat interface, pipeline manager, prompt studio, trace viewer |
| **MinIO Object Storage** | `9000` / `9001` | Raw document binaries storage (`v-res`, `manual-vj` buckets) & console |
| **Qdrant Vector DB** | `6333` / `6335` | 384D/2048D dense vector embeddings with HNSW indexing |
| **OpenSearch** | `9200` | Full-text BM25 lexical inverted index |
| **Neo4j Graph DB** | `7474` / `7687` | Cypher knowledge graph: `(:Document)-[:CONTAINS]->(:Chunk)` |
| **PostgreSQL DB** | `5432` | Relational chunk records, chat sessions, message traces, guardrail configs |
| **Redis / RedisVL** | `6379` | Sub-5ms semantic cache and evaluation job queues |

---

## 4. Operational Runbook & Verification
- **Ingestion Manager Backend**:
  ```bash
  cd rag-ingestion-manager/backend
  uv run uvicorn apps.api.main:app --host 0.0.0.0 --port 8007
  ```
- **Ingestion Manager Frontend**:
  ```bash
  cd rag-ingestion-manager/frontend
  npm run dev -- --port 5173
  ```
- **Retrieval Chat Manager Backend**:
  ```bash
  cd rag-retrieval-chat-manager/backend
  uv run uvicorn apps.rag_api.main:app --host 0.0.0.0 --port 8000
  ```
- **Retrieval Chat Manager Frontend**:
  ```bash
  cd rag-retrieval-chat-manager/frontend
  npm run dev -- --port 5174
  ```

All systems, API routes, models, and interactive visualizers are fully implemented, verified, and accurately documented across `vijay-docs/`.
