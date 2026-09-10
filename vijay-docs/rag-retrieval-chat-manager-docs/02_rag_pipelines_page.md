# 02. RAG Pipelines & Strategy Page (`/pipelines`)

## 1. Page Purpose & Summary

The **RAG Pipelines** (`/pipelines`) page allows administrators to configure hybrid vector retrieval strategies, map Qdrant collections, select dense and sparse embedding models, set chunk size/overlap parameters, and manage vector index collections.

---

## 2. Supported RAG Strategy Architecture

1. **Naive RAG**: Standard dense vector similarity search over text chunks.
2. **HyDE (Hypothetical Document Embeddings)**: Generates hypothetical response documents to align vector spaces before retrieval.
3. **Multi-Query Fusion**: Deconstructs complex user queries into sub-queries, executes parallel searches, and fuses results using Reciprocal Rank Fusion (RRF).
4. **Parent-Child Chunking**: Searches small child chunks for precise vector matches while retrieving parent context blocks for LLM generation.
5. **GraphRAG**: Combines vector retrieval with entity-relation graph traversal.

---

## 3. Key UI Modules & Features

1. **Pipeline Strategy Table**: Displays configured pipelines, Qdrant collection names, dense embedding models, sparse models, chunk size, and chunk overlap settings.
2. **Create Pipeline Wizard**:
   - Step 1: Strategy Selection & Collection Name.
   - Step 2: Dense & Sparse Embedding Model configuration.
   - Step 3: Chunking & Overlap Parameters (e.g. 512 tokens with 64 token overlap).
3. **Pipeline Index & Sync Controls**: Re-index trigger and collection deletion capabilities.

---

## 4. API Endpoint Reference

- **`listPipelines()`**: `GET /api/rag/pipelines` — Returns list of configured pipelines and Qdrant collections.
- **`getPipelineOptions()`**: `GET /api/rag/pipelines/options` — Returns available embedding models and strategies.
- **`createPipeline(body)`**: `POST /api/rag/pipelines` — Creates pipeline configuration in database and provisions Qdrant collection.
- **`deletePipeline(id)`**: `DELETE /api/rag/pipelines/{id}` — Removes pipeline configuration and purges collection.
