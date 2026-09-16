# 02 — RAG Pipelines Management Page

## 1. Executive Summary & Page Purpose
The **RAG Pipelines Management Page** (`PipelinesPage.tsx`, route: `/pipelines`) enables AI engineers to define, fine-tune, and benchmark multi-stage RAG retrieval architectures. Users can configure retrieval strategies (Dense Vector, Sparse BM25, Hybrid, Multimodal, or Metadata-filtered), adjust dense/sparse weights, select embedding models (`bge-small-en-v1.5`, `openai/text-embedding-3-small`), choose rerankers (`cohere/rerank-v3.5`, `bge-reranker-large`, `noop`), bind generator models (`gpt-4o`, `claude-3-5-sonnet`, `deepseek-chat`, `ollama/llama3`), and link Knowledge Store profiles.

---

## 2. RAG Pipeline Topology & Stage Configuration

```
+-----------------------------------------------------------------------------------------------+
|  1. User Query Input -> Query Preprocessing & Multi-Modal Vision Expansion                     |
+-----------------------------------------------+-----------------------------------------------+
                                                |
                                                v
+-----------------------------------------------------------------------------------------------+
|  2. Hybrid Retrieval Stage                                                                    |
|     - Dense Vector Search (Qdrant HNSW cosine similarity, top_k = 20)                         |
|     - Sparse Lexical Search (OpenSearch BM25 / FastEmbed SPLADE, top_k = 20)                  |
|     - Reciprocal Rank Fusion (RRF) / Alpha Weighted Combination (α * dense + (1-α) * sparse)   |
+-----------------------------------------------+-----------------------------------------------+
                                                |
                                                v
+-----------------------------------------------------------------------------------------------+
|  3. Cross-Encoder Reranking Stage                                                             |
|     - LiteLLM / Cohere / BGE Reranker scoring (selects top_n = 5 chunks)                      |
|     - Minimum Relevance Score Threshold filtering (e.g. score >= 0.45)                        |
+-----------------------------------------------+-----------------------------------------------+
                                                |
                                                v
+-----------------------------------------------------------------------------------------------+
|  4. Dynamic Prompt Assembly & Generation Stage                                                |
|     - Context Injection: System Prompt + Cited Chunks + Session History                       |
|     - LLM Inference via LiteLLM Gateway (Streaming SSE or non-streaming JSON)                 |
+-----------------------------------------------+-----------------------------------------------+
                                                |
                                                v
+-----------------------------------------------------------------------------------------------+
|  5. Guardrails & Telemetry Span Tracing (Self-Corrective Routing / Presidio PII Masking)      |
+-----------------------------------------------------------------------------------------------+
```

---

## 3. UI Layout & Visual Components

```
+-----------------------------------------------------------------------------------------------+
|  RAG Pipeline Management                                                                      |
|  Configure retrieval parameters, reranker models, and LLM generator endpoints.               |
|  [ + New Pipeline ]  [ Refresh ]                                                              |
+-----------------------------------------------------------------------------------------------+
|  Active Pipelines (2)                                                                         |
|                                                                                               |
|  +------------------------------------------------------------------------------------------+ |
|  | Enterprise Hybrid RAG Pipeline (v-res)                                [ ACTIVE / DEFAULT ] |
|  | Strategy: HYBRID | Embedding: bge-small-en-v1.5 (384D) | Reranker: cohere/rerank-v3.5       |
|  | Generator: gpt-4o | Top-K: 20 -> Top-N: 5 | Alpha: 0.70 Dense / 0.30 Sparse                 |
|  | Knowledge Profile: Enterprise Multi-RAG Fanout Profile (v-res & manual-vj)                |
|  |                                                                                          | |
|  | [ 🚀 Test Run ]  [ ✏️ Edit Config ]  [ 📊 View Analytics ]  [ 🗑️ Delete ]                 | |
|  +------------------------------------------------------------------------------------------+ |
+-----------------------------------------------------------------------------------------------+
```

---

## 4. Backend APIs & Contracts

| Method | Endpoint | Description | Request / Response |
|---|---|---|---|
| `GET` | `/pipelines` | Lists all pipelines | `list[PipelineRecord]` |
| `POST` | `/pipelines` | Creates a new pipeline | `CreatePipelineRequest` -> `PipelineRecord` |
| `GET` | `/pipelines/{id}` | Retrieves full pipeline config & runs | `PipelineRecord` |
| `PUT` | `/pipelines/{id}` | Updates pipeline hyperparameters | `UpdatePipelineRequest` -> `PipelineRecord` |
| `DELETE` | `/pipelines/{id}` | Deletes pipeline | `{"status": "deleted"}` |
| `POST` | `/pipelines/{id}/runs` | Executes benchmark test run against pipeline | `PipelineRunRecord` |

### Sample Pipeline Configuration Payload (`POST /pipelines`)
```json
{
  "name": "Enterprise Hybrid RAG Pipeline",
  "description": "Production hybrid pipeline for HR resume and technical document search",
  "rag_strategy": "hybrid",
  "embedding_model": "BAAI/bge-small-en-v1.5",
  "sparse_embedding_model": "prithivida/Splade_PP_en_v1",
  "reranker_model": "cohere/rerank-v3.5",
  "generator_model": "gpt-4o",
  "retrieval_limit": 20,
  "rerank_top_n": 5,
  "hybrid_alpha": 0.7,
  "knowledge_profile_id": "3695cb61-e728-4bf1-91f8-cf249d593c6b"
}
```
