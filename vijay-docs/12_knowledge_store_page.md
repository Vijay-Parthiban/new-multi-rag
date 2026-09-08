# Page Documentation: Knowledge Store Manager (`KnowledgeStorePage.tsx`)

## 1. Overview & Purpose

The **Knowledge Store Manager** (`/knowledge-store`) enables enterprise teams to link MinIO document source buckets (such as Google Drive, Amazon S3, Local Folders) to 5 enterprise 2026 RAG destination categories simultaneously via a **Universal Multi-Sink Fanout Ingestion Engine**.

### 5 Enterprise 2026 RAG Destination Categories
1. **Vector Engine**: Qdrant (`knowledge_qdrant_collection` dense similarity search with HNSW graph indexing & scalar/binary quantization).
2. **Lexical & Sparse Search**: OpenSearch (`knowledge_lexical_index` BM25 keyword matching & SPLADE/BGE-M3 learned sparse vector inverted indexing).
3. **Knowledge Graph Store**: Neo4j (`bolt://localhost:7687` entity-relationship extraction & hierarchical community report summaries for GraphRAG).
4. **Multi-Model Relational DB**: PostgreSQL with pgvector/pgvectorscale (`knowledge_vector_records` co-located metadata, document ownership, ACLs, and vector embeddings).
5. **Semantic Cache & Summary Stores**: RedisVL (`knowledge_cache` parent-child chunk mapping, RAPTOR recursive summary trees & semantic prompt caching).

---

## 2. Page & Component Architecture

- **Route**: `/knowledge-store`
- **Main Component**: `KnowledgeStorePage.tsx` (`ingestion-workspace/ingestion-frontend/src/pages/KnowledgeStorePage.tsx`)
- **API Endpoints**: `/api/knowledge-profiles` (`ingestion-workspace/ingestion-backend/apps/api/routes/knowledge.py`)
- **Fanout Ingestion Core**: `src/ingestion_service/core/universal_fanout.py`
- **Database Models**: `KnowledgeProfile`, `KnowledgeProfileSource`, `KnowledgeDestinationConfig` (`src/shared/db/models.py`)

---

## 3. Visual Layout & UI Controls

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Header: Knowledge Store Manager | 2026 Engine Badge   [Refresh] [+ New Profile]│
├─────────────────────────────────────────────────────────────────────────────┤
│ Metrics Overview Grid:                                                       │
│ ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐ ┌────────────┐ │
│ │ Total Profiles   │ │ Connected Buckets│ │ Active RAG Sinks │ │ Architecture│ │
│ │        1         │ │        2         │ │        5         │ │5-Sink Fanout│ │
│ └──────────────────┘ └──────────────────┘ └──────────────────┘ └────────────┘ │
├─────────────────────────────────────────────────────────────────────────────┤
│ Knowledge Profiles List:                                                     │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ Universal Resume 2026 Knowledge Profile                 ● SUCCESS       │ │
│ │                                                        [Sync All Sinks] │ │
│ │ LINKED MINIO SOURCE BUCKETS (2):                                        │ │
│ │  - GDrive NiFi Source 1788811754 (source-gdrive-nifi-source-1788811754) │ │
│ │  - my-resumes (source-my-resumes-d29f4670)                              │ │
│ │                                                                         │ │
│ │ CONFIGURED DESTINATION STORES (5-SINK):                                 │ │
│ │  1. Qdrant [ACTIVE] - Collection: knowledge_qdrant_collection [Test Conn]│ │
│ │  2. OpenSearch [ACTIVE] - Index: knowledge_lexical_index     [Test Conn]│ │
│ │  3. Neo4j [ACTIVE] - URI: bolt://localhost:7687             [Test Conn]│ │
│ │  4. PostgreSQL (pgvector) [ACTIVE] - Table: vector_records  [Test Conn]│ │
│ │  5. RedisVL [ACTIVE] - Cache Prefix: knowledge_cache        [Test Conn]│ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. API Specification & Endpoints

| Method | Path | Description |
| :--- | :--- | :--- |
| `GET` | `/api/knowledge-profiles` | List all knowledge profiles with linked source buckets & destination configs |
| `POST` | `/api/knowledge-profiles` | Create a new knowledge profile with source links & destination store settings |
| `GET` | `/api/knowledge-profiles/{id}` | Retrieve details of a specific knowledge profile |
| `PUT` | `/api/knowledge-profiles/{id}` | Update knowledge profile settings, source links, or destination parameters |
| `DELETE` | `/api/knowledge-profiles/{id}` | Delete a knowledge profile and un-link destinations |
| `GET` | `/api/knowledge-profiles/destinations/options` | Retrieve available RAG destination store templates & schemas |
| `POST` | `/api/knowledge-profiles/{id}/test-connection` | Test live connectivity to Qdrant, OpenSearch, Neo4j, Postgres, or RedisVL |
| `POST` | `/api/knowledge-profiles/{id}/sync` | Trigger asynchronous multi-sink fanout ingestion across all 5 destinations |

---

## 5. Multi-Sink Fanout Engine Workflow

1. **Trigger**: User clicks **Sync All Sinks** or triggers `POST /api/knowledge-profiles/{id}/sync`.
2. **Background Task**: FastAPI enqueues `_background_fanout_sync` using non-blocking `BackgroundTasks`. Profile status transitions to `"syncing"`.
3. **Source Processing**:
   - Engine reads all linked `KnowledgeProfileSource` records and retrieves corresponding MinIO buckets (`minio_bucket`).
   - Lists and streams object bytes using MinIO S3 client (`s3_client.get_object`).
4. **Document Extraction & Vector Embedding**:
   - Parses document pages (e.g. PDF resume files) using PyMuPDF `fitz`.
   - Generates 2048-dimensional dense vector embeddings using FastEmbed (`BAAI/bge-large-en-v1.5`).
5. **Universal Fanout Ingestion**:
   - **Vector Engine (Qdrant)**: Upserts dense vector points with metadata payload into `knowledge_qdrant_collection`.
   - **Lexical Search (OpenSearch)**: Prepares BM25 index docs.
   - **Knowledge Graph (Neo4j)**: Prepares entity-relationship triples.
   - **Relational DB (PostgreSQL pgvector)**: Inserts vector records.
   - **Semantic Cache (RedisVL)**: Prepares summary cache entries.
6. **Completion**: Updates destination status to `"synced"` and profile status to `"success"`.

---

## 6. How to Run & Verify

1. **Backend Server**: Run `apps/api/main.py` on port `8007`.
2. **Frontend UI**: Run Vite dev server on port `5173`. Navigate to `http://localhost:5173/knowledge-store`.
3. **Connection Test**: Click **Test Connection** under any destination card (e.g. Qdrant) to observe green `"Connected"` badge.
4. **Execution**: Click **Sync All Sinks** to initiate background fanout ingestion across all linked buckets.
