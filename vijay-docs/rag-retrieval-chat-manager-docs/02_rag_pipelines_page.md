# 02. RAG Pipelines & Strategy Page (`/pipelines`)

## 1. Page Purpose & Summary

The **RAG Pipelines** (`/pipelines`) page allows administrators to configure hybrid vector retrieval strategies, create Qdrant collection mappings, select dense/sparse embedding models, tune chunking strategies, and monitor vector index status.

---

## 2. Supported RAG Strategy Architecture

1. **Naive RAG**: Standard dense vector similarity search over text chunks.
2. **HyDE (Hypothetical Document Embeddings)**: Generates hypothetical response documents to align vector spaces before retrieval.
3. **Multi-Query Fusion**: Deconstructs complex user queries into sub-queries, executes parallel searches, and fuses results using Reciprocal Rank Fusion (RRF).
4. **Parent-Child Chunking**: Searches small child chunks for precise vector matches while retrieving parent context blocks for LLM generation.
5. **GraphRAG**: Combines vector retrieval with entity-relation graph traversal.

---

## 3. Key UI Modules & Features

1. **Pipeline Strategy Table**: Displays active pipelines, Qdrant collection names, dense embedding model (`BAAI/bge-large-en-v1.5`, `text-embedding-3-large`), sparse model (`Qdrant/bm25`), and chunk size settings.
2. **Create Pipeline Wizard**:
   - Step 1: Strategy Selection & Collection Name.
   - Step 2: Dense & Sparse Embedding Model configuration.
   - Step 3: Chunking & Overlap Parameters (e.g. 512 tokens with 64 token overlap).
3. **Pipeline Sync & Index Actions**: Trigger re-indexing or purge vector collections.

---

## 4. API Endpoint Reference

- **`listPipelines()`**: `GET /api/rag/pipelines`
- **`getPipelineOptions()`**: `GET /api/rag/pipelines/options`
- **`createPipeline(body)`**: `POST /api/rag/pipelines`
- **`deletePipeline(id)`**: `DELETE /api/rag/pipelines/:id`
