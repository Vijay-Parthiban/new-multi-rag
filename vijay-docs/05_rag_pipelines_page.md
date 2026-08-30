# Page Documentation: RAG Pipelines Management (`PipelinesPage.tsx`)

## 1. Overview & Purpose

The **RAG Pipelines Management Page** (`/pipelines`) allows platform engineers and data architects to construct, configure, execute, and monitor end-to-end vector indexing pipelines. Pipelines orchestrate how raw documents and web content are parsed, chunked, embedded, and mapped into specific Qdrant vector collections.

---

## 2. Page Architecture & Visual Layout

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Header: RAG Pipelines | 2026 Engine Badge              [+ Create Pipeline]  │
├─────────────────────────────────────────────────────────────────────────────┤
│ Active Pipelines Bento Grid:                                                │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ 🔮 Default Vector Pipeline                           ● ACTIVE [Run ➔]   │ │
│ │ Qdrant Collection: rag-documents | RAG Strategy: Hybrid (Dense + Sparse)│ │
│ │ Embedding Model: text-embedding-3-small (1536d)                         │ │
│ │ Chunk Size: 1000 tokens | Overlap: 120 tokens                           │ │
│ │ Attached Directories: rag-raw-documents, source-engineering-knowledge   │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────────────┤
│ Pipeline Configuration & Creation Form:                                     │
│  ┌─────────────────────────────────┬─────────────────────────────────────┐  │
│  │ Pipeline Name & Strategy        │ Chunking & Vector Settings          │  │
│  │ Name: [ Production RAG Index  ] │ Chunk Size:    [ 1000 ] tokens     │  │
│  │ Strategy: [ Hybrid Search ▾   ] │ Chunk Overlap: [  120 ] tokens     │  │
│  │ Dense Model:  [ text-embedding-3-small ▾ ]                              │  │
│  │ Sparse Model: [ Qdrant/bm25 ▾ ] │ Qdrant Collection: [ rag-docs-v2 ]  │  │
│  └─────────────────────────────────┴─────────────────────────────────────┘  │
│  Selected Input Directories: [x] rag-raw-documents  [x] source-engineering   │
│  Attached Connectors:        [x] Google Drive      [x] AWS S3 Bucket       │
├─────────────────────────────────────────────────────────────────────────────┤
│ Execution History & Live Runs Table:                                        │
│ ┌── Run ID ──┬── Trigger ──────┬── Status ──────┬── Documents ──┬── Duration ┐│
│ │ run-9901   │ Scheduled Sync │ ● COMPLETED    │ 142 files     │ 42 sec     │
│ │ run-9884   │ Manual Run     │ ● COMPLETED    │ 18 files      │ 12 sec     │
│ └────────────┴────────────────┴────────────────┴───────────────┴────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Key Pipeline Configuration Parameters

### 3.1 RAG Search Strategies
- **Dense Vector Search (`dense`)**: Standard high-dimensional semantic search using vector cosine similarity.
- **Hybrid Search (`hybrid`)**: Combines dense semantic vector search with sparse BM25 keyword matching for optimal recall.
- **Multimodal (`multimodal`)**: Encodes both text chunks and document images (charts, diagrams) into joint vector spaces.
- **Sparse Vector Search (`sparse`)**: BM25 frequency-based sparse vector generation.

### 3.2 Chunking Configuration
- **Chunk Size**: Specifies maximum character/token length per text segment (e.g. 512, 1000, 2048).
- **Chunk Overlap**: Specifies token overlap between adjacent sliding windows (e.g. 64, 120, 256) to maintain context boundaries across chunk splits.

### 3.3 Web Scraper Integration Settings
Pipelines support inline integration with Crawl4AI web scraper seeds:
- `web_scraper_enabled`: Toggle active scraping during pipeline execution.
- `scraper_seed_url`: Root URL to begin web crawling (e.g., `https://docs.example.com`).
- `scraper_max_depth`: Maximum depth for hyperlink crawling (e.g., 2 or 3).
- `scraper_max_pages`: Safety cap on total crawled pages (e.g., 50).
- `scraper_mode`: Headless Playwright (`playwright`) or fast HTTP client (`httpx`).

---

## 4. API Endpoints & Request Schemas

### 4.1 `GET /api/pipelines`
- **Description**: Returns all configured RAG pipelines.

### 4.2 `GET /api/pipelines/options`
- **Description**: Returns available embedding models, sparse models, and chunking options.
- **Response Schema (`PipelineOptions`)**:
```json
{
  "embedding_models": [
    "text-embedding-3-small",
    "text-embedding-3-large",
    "cohere-embed-english-v3.0",
    "bge-m3"
  ],
  "sparse_models": [
    "Qdrant/bm25",
    "splade-v2"
  ],
  "rag_strategies": [
    "dense",
    "hybrid",
    "sparse",
    "multimodal"
  ]
}
```

### 4.3 `POST /api/pipelines`
- **Description**: Creates a new vector indexing pipeline.
- **Request Body (`CreatePipelineRequest`)**:
```json
{
  "name": "Production Vector Pipeline",
  "description": "Hybrid dense + sparse RAG pipeline for engineering docs",
  "rag_strategy": "hybrid",
  "embedding_model": "text-embedding-3-small",
  "sparse_embedding_model": "Qdrant/bm25",
  "modality": "text",
  "chunk_size": 1000,
  "chunk_overlap": 120,
  "qdrant_collection": "production-rag-docs",
  "directories": ["rag-raw-documents"],
  "sources": ["a8541818-bb30-44b5-8956-75e0e5ca7d88"],
  "web_scraper_enabled": true,
  "scraper_seed_url": "https://docs.example.com",
  "scraper_max_depth": 2,
  "scraper_max_pages": 50,
  "scraper_mode": "httpx"
}
```

### 4.4 `POST /api/pipelines/:id/runs`
- **Description**: Triggers immediate execution of a pipeline sync run (`sync_pipeline`) via Redis job queue.

---

## 5. Pipeline Vector Synchronization Engine (`sync_runner.py`)

The backend pipeline reconciliation engine (`sync_runner.py`) automatically synchronizes Qdrant vector collections with connected data:
1. **Multi-Source Reconciliation**: Reconciles local directory files (`FileRecord`) and external connector files stored in MinIO per-source buckets (`Source.minio_bucket`).
2. **Deterministic Virtual UUIDs**: Assigns deterministic virtual UUIDs (`uuid.uuid5(uuid.NAMESPACE_URL, f"minio://{source.id}/{file_key}")`) for source-backed objects, ensuring point isolation in Qdrant.
3. **Content Hash Deduplication**: Compares file content hashes against `IndexedFile` tracking records to prevent duplicate vector upserts.
4. **Live Pathway Event Monitoring**: Integrates with Pathway MinIO watcher (`start_minio_monitor` / `watch_minio_bucket`) to trigger instant re-indexing upon object upload or deletion.
5. **Deletion Reconciliation**: Automatically removes orphaned vector chunk points from Qdrant when files are deleted from MinIO or unlinked from pipelines.

## 6. State Management & React Hooks

- **`usePipelines`**: State hook managing `pipelines`, `directories`, `sources`, `runs`, `selectedPipelineId`, and `activePipelineStats`.
- **Directory & Source Linker**: Allows linking multiple MinIO storage buckets and external connectors to a single output Qdrant vector collection.

---

## 7. Step-by-Step Run & Verification
2. **Configure New Pipeline**:
   - Enter Name: `Knowledge Base Pipeline`.
   - Select RAG Strategy: `Hybrid`.
   - Select Dense Embedding Model: `text-embedding-3-small`.
   - Set Chunk Size: `1000`, Overlap: `120`.
   - Specify Qdrant Collection: `kb-vectors`.
   - Check target directories and sources.
   - Click `Create Pipeline`.
3. **Trigger Manual Execution**:
   - Locate the newly created pipeline in the active list.
   - Click `Run Pipeline`.
   - Observe the live execution record appear in the Pipeline Runs table with status updating to `COMPLETED`.
