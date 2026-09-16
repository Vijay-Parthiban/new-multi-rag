# 04 — Knowledge Store Fanout & Multi-Sink Visualizer Page

## 1. Executive Summary & Page Purpose
The **Knowledge Store Fanout Page** (`KnowledgeStorePage.tsx`, route: `/knowledge-store`) is the multi-sink orchestration hub of the RAG ingestion pipeline. It allows administrators to bind source document repositories (MinIO buckets, directory workspaces) to **5 enterprise destination sinks**, execute parallel fanout synchronizations via `universal_fanout.py`, and inspect live indexed representations using dedicated **Interactive Visualizer Modals** for Vector, Lexical, Graph, Relational, and Semantic Cache layers.

---

## 2. 5-Destination Universal Fanout Architecture

```
                                  +-----------------------+
                                  |  MinIO Object Store   |
                                  |  (v-res & manual-vj)  |
                                  +-----------+-----------+
                                              |
                                              v
                              +-------------------------------+
                              |  Universal Fanout Engine      |
                              |  (universal_fanout.py)        |
                              |  - Markdown Parsing           |
                              |  - Recursive Text Chunking    |
                              |  - Dense 384/2048D Embeddings |
                              +---------------+---------------+
                                              |
      +-------------------+-------------------+-------------------+-------------------+-------------------+
      |                   |                   |                   |                   |                   |
      v                   v                   v                   v                   v                   v
+------------+     +---------------+     +-----------+     +---------------+     +---------------+
| 1. Qdrant  |     | 2. OpenSearch |     | 3. Neo4j  |     | 4. PostgreSQL |     | 5. RedisVL    |
| Vector DB  |     | BM25 Lexical  |     | Knowledge |     | Relational    |     | Semantic      |
| (Dense HNSW|     | (Inverted     |     | Graph     |     | Chunks        |     | Cache (Sub-5ms|
| Embeddings)|     | Index)        |     | (Entities)|     | (Metadata)    |     | Exact Match)  |
+------------+     +---------------+     +-----------+     +---------------+     +---------------+
```

### Destination Sink Details
1. **Qdrant Vector DB (`vector_qdrant`)**:
   - **Role**: Dense vector similarity search via HNSW indexing.
   - **Dimensions**: 384D (`BAAI/bge-small-en-v1.5` / `all-MiniLM-L6-v2`) or 2048D multimodal.
   - **Collection**: `rag_documents_vres` / `documents_vres`.
2. **OpenSearch Lexical Search (`lexical_opensearch`)**:
   - **Role**: Full-text BM25 keyword retrieval, analyzer tokenization, and exact term frequency matching.
   - **Index**: `rag_lexical_vres` / `documents_vres`.
3. **Neo4j Knowledge Graph (`graph_neo4j`)**:
   - **Role**: Entity relationship extraction, Document-Chunk hierarchies, and graph traversal.
   - **Cypher Labels**: `(:Document {id, name, path}) -[:CONTAINS]-> (:Chunk {index, text, hash})`.
4. **PostgreSQL / PGVector (`relational_pgvector`)**:
   - **Role**: Relational persistence of raw chunk text, metadata JSONB, token counts, and relational queries.
   - **Table**: `knowledge_chunks` / `document_chunks`.
5. **RedisVL Semantic Cache (`cache_redisvl`)**:
   - **Role**: Sub-5ms low-latency semantic cache and query deduplication.
   - **Index / Prefix**: `rag_cache:*` with semantic distance thresholds.

---

## 3. UI Layout & Visual Components

```
+-------------------------------------------------------------------------------------------------------+
|  Knowledge Store Manager                                                                              |
|  Universal Multi-Sink Fanout Engine — Route MinIO documents to 5 enterprise RAG destinations.         |
|  [ + New Knowledge Profile ]  [ Refresh ]                                                             |
+-------------------------------------------------------------------------------------------------------+
|  Metric Banner: [ Total Profiles: 1 ] [ Connected Buckets: 2 ] [ Active Sinks: 5 ] [ Sinks: 5 Sinks ] |
+-------------------------------------------------------------------------------------------------------+
|  Profile: Enterprise Multi-RAG Fanout Profile                       Status: [ SUCCESS / SYNCED ]      |
|  Sources: [ 🪣 v-res (10 files) ]  [ 📁 manual-vj (1 file) ]                                         |
|  Actions: [ ⚡ Sync All Sinks ]  [ 🔭 Multi-Sink Visualizer ]  [ ✏️ Edit ]  [ 🗑️ Delete ]             |
|                                                                                                       |
|  Configured Destination Sinks:                                                                        |
|  +------------------------+  +------------------------+  +------------------------+                   |
|  | 🔮 Qdrant Vector DB    |  | 🔍 OpenSearch BM25     |  | 🕸️ Neo4j Graph        |                   |
|  | Host: localhost:6333   |  | Host: localhost:9200   |  | URI: bolt://...:7687   |                   |
|  | Collection: v-res      |  | Index: rag_lexical     |  | Database: neo4j        |                   |
|  | [Test Link] [🔭Inspect]|  | [Test Link] [🔭Inspect]|  | [Test Link] [🔭Inspect]|                   |
|  +------------------------+  +------------------------+  +------------------------+                   |
|  +------------------------+  +------------------------+                                               |
|  | 🐘 PostgreSQL Chunks   |  | ⚡ RedisVL Cache       |                                               |
|  | Table: knowledge_chunks|  | Prefix: rag_cache:*    |                                               |
|  | [Test Link] [🔭Inspect]|  | [Test Link] [🔭Inspect]|                                               |
|  +------------------------+  +------------------------+                                               |
+-------------------------------------------------------------------------------------------------------+
```

---

## 4. Live Multi-Sink Visualizers

When clicking **"🔭 Multi-Sink Visualizer"** or **"🔭 Inspect Store"**, the interactive visualizer modal (`DestinationVisualizerModal.tsx`) launches with 5 tabbed inspectors:

1. **Vector Search (Qdrant) Visualizer (`VectorVisualizer.tsx`)**:
   - Displays real-time vector point count, collection status, and vector dimensions.
   - Computes a 2D PCA/Scatter projection with interactive cluster point inspection and hover tooltips.
   - Lists point payloads, chunk IDs, source document names, and vector distances.
2. **Lexical Search (OpenSearch) Visualizer (`LexicalVisualizer.tsx`)**:
   - Shows index document counts, store size, and primary shard allocations.
   - Displays top keyword terms and BM25 term frequency histograms.
   - Allows interactive keyword search testing with highlighted lexical matches.
3. **Knowledge Graph (Neo4j) Visualizer (`GraphVisualizer.tsx`)**:
   - Force-directed interactive canvas rendering Document nodes, Chunk nodes, and Entity links.
   - Drag, zoom, node selection, and side-panel inspection of node properties and Cypher relationships.
4. **Relational Chunks (PostgreSQL) Visualizer (`RelationalVisualizer.tsx`)**:
   - Tabular view of raw partitioned chunk records.
   - Columns: Chunk Index, Document ID, Token Count, Content Excerpt, and Creation Timestamp.
   - Text search filter and raw JSON metadata explorer.
5. **Semantic Cache (RedisVL) Visualizer (`CacheVisualizer.tsx`)**:
   - Real-time cache metrics: Memory used, total cached keys, and hit rate gauge.
   - Key explorer listing cached prompt-response pairs, TTLs, and vector similarity thresholds.

---

## 5. Backend APIs & Inspection Contracts

| Method | Endpoint | Description | Response Model |
|---|---|---|---|
| `GET` | `/api/knowledge-profiles` | Lists all routing profiles with sink configs | `list[KnowledgeProfile]` |
| `POST` | `/api/knowledge-profiles` | Creates a new fanout routing profile | `KnowledgeProfileCreate` |
| `POST` | `/api/knowledge-profiles/{id}/sync` | Triggers parallel universal fanout sync across 5 sinks | `{"status": "success", "synced_files": int}` |
| `POST` | `/api/knowledge-profiles/{id}/test/{dest_type}` | Tests connection credentials for a specific sink | `{"status": "success" \| "error"}` |
| `GET` | `/api/knowledge-profiles/{id}/inspect/{dest_type}` | Retrieves live sink data for the UI visualizer | `SinkInspectionPayload` |

### Sample Live Inspection Output (`GET /inspect/vector_qdrant`)
```json
{
  "destination_type": "vector_qdrant",
  "collection_name": "documents_vres",
  "total_points": 73,
  "status": "green",
  "points": [
    {
      "id": "c6239121-0e10-4107-8898-d89069d3e8e1",
      "vector": [0.0381, -0.0124, 0.0912, "...", -0.0418],
      "payload": {
        "document_name": "resume_alex_chen.pdf",
        "chunk_index": 0,
        "text": "Alex Chen — Senior AI Engineer with extensive experience in Qdrant and LLM orchestration...",
        "source_id": "2da1c0d5-5727-4632-9cb9-009c91d4e0e4"
      }
    }
  ]
}
```
