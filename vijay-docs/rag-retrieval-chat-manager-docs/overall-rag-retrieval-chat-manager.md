# Overall Architecture — RAG Retrieval & Chat Manager

## 1. System Overview
`rag-retrieval-chat-manager` is the intelligent querying, retrieval orchestration, reranking, generation, safety guardrail, and evaluation platform in the `new-multi-rag` ecosystem. It leverages hybrid vector retrieval (Qdrant HNSW + OpenSearch BM25), LiteLLM cross-encoder rerankers, LiteLLM/Ollama generator models, Microsoft Presidio guardrail safety checks, and continuous Ragas offline evaluation suites.

---

## 2. Complete Component Architecture

```
+---------------------------------------------------------------------------------------------------+
|                                  USER / API CONSUMER INTERFACE                                    |
|  [ Web UI: Vite/React (Port 5174) ]  [ Streaming SSE Chat ]  [ REST APIs (Port 8000) ]            |
+-------------------------------------------------+-------------------------------------------------+
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
|                                 RAG RETRIEVAL & CHAT BACKEND                                      |
|  +---------------------------+  +-------------------------------+  +---------------------------+  |
|  | Input Safety Guardrails   |  | Hybrid Retrieval Engine       |  | Cross-Encoder Reranker    |  |
|  | - Presidio PII/SPI Redact |  | - vector_core: Qdrant dense   |  | - reranker_core: LiteLLM  |  |
|  | - Banned words & Toxicity |  | - retrieval_core: OpenSearch  |  | - Cohere v3.5 / BGE large |  |
|  | - Prompt Injection Guard  |  | - Reciprocal Rank Fusion      |  | - Score threshold filter  |  |
|  +---------------------------+  +-------------------------------+  +---------------------------+  |
|                                                 |                                                 |
|                                                 v                                                 |
|  +---------------------------+  +-------------------------------+  +---------------------------+  |
|  | Output Safety Guardrails  |  | Generation Core (LLM Engine)  |  | Prompt Studio Core        |  |
|  | - Presidio output mask    |  | - generation_core: Generator  |  | - dynamic variables       |  |
|  | - Toxic response blocker  |  | - Vision multimodal support   |  | - context block builder   |  |
|  | - Hallucination audit     |  | - GPT-4o, Claude 3.5, Ollama  |  | - version history         |  |
|  +---------------------------+  +-------------------------------+  +---------------------------+  |
|                                                 |                                                 |
|                                                 v                                                 |
|  +---------------------------+  +-------------------------------+  +---------------------------+  |
|  | OpenTelemetry Tracing     |  | Offline Ragas Evaluation      |  | Background Eval Worker    |  |
|  | - Span waterfall trees    |  | - eval_core: Faithfulness     |  | - Async batch execution   |  |
|  | - Per-message latency     |  | - Answer relevance, precision |  | - Celery / Redis queue    |  |
|  +---------------------------+  +-------------------------------+  +---------------------------+  |
+-------------------------------------------------+-------------------------------------------------+
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
|                                     PERSISTENCE & STORAGE                                         |
|  [ PostgreSQL: Chats, Sessions, Traces, Guardrails, Evals ]  [ RedisVL: Semantic Cache ]           |
+---------------------------------------------------------------------------------------------------+
```

---

## 3. Modular Library Decomposition (`libs/`)
The backend is structured into modular Python libraries:
- **`libs/rag-core`**: High-level RAG pipeline orchestrator and execution router (`pipeline.py`, `schemas.py`).
- **`libs/vector-core`**: Qdrant vector client, dense embedding generation, SPLADE sparse vectors, payload hit mappers (`qdrant_store.py`, `search.py`, `embedding_client.py`).
- **`libs/retrieval-core`**: Hybrid search fusion, OpenSearch lexical search, and multi-source hit aggregators (`retriever.py`, `hit_mapper.py`).
- **`libs/reranker-core`**: LiteLLM and Cohere cross-encoder rerankers with noop fallback (`litellm_reranker.py`, `noop.py`).
- **`libs/generation-core`**: Prompt assembling, context block formatting, LLM streaming generators, and vision multimodal processors (`generator.py`, `prompt_builder.py`, `vision_generator.py`).
- **`libs/eval-core`**: Ragas and DeepEval metrics runners (Faithfulness, Relevancy, Precision, Recall, Red-team guardrail runners) (`runner.py`, `ragas_client.py`, `generation_metrics.py`).
- **`libs/database`**: SQLAlchemy models and repositories for chats, messages, evaluation runs, guardrail policies, and traces (`rag_db/models/`, `rag_db/repositories/`).
- **`libs/shared`**: Cross-cutting utilities, configuration settings, Presidio guardrail client, tracing context, and logging (`rag_shared/`).

---

## 4. Key Invariants & Operational Guarantees
1. **Safety Interception First**: Guardrail safety checks run before vector search, preventing unauthorized prompt injection attacks from consuming embedding or LLM compute.
2. **Deterministic Offline Evaluation**: Golden dataset benchmarks evaluate fixed context sets to produce stable, reproducible Ragas metric baselines.
3. **End-to-End Tracing**: Every conversational exchange produces a complete span tree recording execution times across retrieval, reranking, generation, and guardrails.
