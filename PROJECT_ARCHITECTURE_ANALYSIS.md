# COMPREHENSIVE PROJECT ARCHITECTURE ANALYSIS
**Generated:** 2026-09-11  
**Project:** Multi-RAG Enterprise Platform

---

## PROJECT OVERVIEW

This is a **dual-application enterprise RAG platform** consisting of two main systems:

1. **`rag-ingestion-manager`** — Document ingestion, multi-source connectors, and 5-destination fanout
2. **`rag-retrieval-chat-manager`** — RAG chat, multi-strategy retrieval, evaluation, and AI guardrails

Both projects share a common architecture pattern:
- **Backend:** FastAPI + SQLAlchemy + AsyncIO
- **Frontend:** React + TypeScript + Vite
- **Storage:** PostgreSQL (retrieval), SQLite (ingestion), MinIO S3, Qdrant, OpenSearch, Neo4j, Redis
- **Queue:** Redis (RQ) for async job processing

---

## 1. RAG-INGESTION-MANAGER PROJECT

### Purpose
**Document ingestion, multi-source CDC connectors, universal 5-sink fanout engine**

### Backend Architecture (`rag-ingestion-manager/backend/`)

#### Directory Structure
```
backend/
├── apps/                          # Multi-process applications
│   ├── api/                       # FastAPI REST API server (port 8007)
│   │   ├── main.py               # FastAPI app initialization, CORS, lifespan
│   │   ├── exceptions.py         # Global error handlers
│   │   └── routes/               # API endpoint modules
│   │       ├── sources.py        # CRUD for external data sources (MinIO buckets + connectors)
│   │       ├── knowledge.py      # Knowledge Profile CRUD (5-sink fanout configs)
│   │       ├── pipelines.py      # RAG pipeline CRUD (embedding models, Qdrant collections)
│   │       ├── files.py          # File metadata & operations
│   │       ├── uploads.py        # Chunked file upload handling
│   │       └── directories.py    # Virtual folder management
│   ├── pathway_worker/           # Pathway CDC connector worker
│   │   └── main.py               # Airbyte/Pathway real-time streaming
│   └── worker/                   # Background job worker (RQ)
│       ├── main.py               # RQ worker process
│       └── scheduler.py          # Periodic job scheduler
├── src/                          # Core business logic modules
│   ├── shared/                   # Shared infrastructure
│   │   ├── db/                   # SQLAlchemy models & session
│   │   │   ├── models.py         # Source, Pipeline, Directory, FileRecord, SyncJob, KnowledgeProfile
│   │   │   ├── session.py        # AsyncSession factory
│   │   │   └── migrate.py        # Alembic migration runner
│   │   ├── storage/              # MinIO S3 client
│   │   │   └── s3_client.py      # Boto3 async wrapper with 1.0s socket timeout
│   │   ├── queue/                # Redis queue client
│   │   │   └── client.py         # RQ queue wrapper
│   │   ├── config/               # Settings & env
│   │   │   └── settings.py       # Pydantic settings (DATABASE_URL, MINIO_*, QDRANT_*, etc.)
│   │   └── auth.py               # API key verification middleware
│   ├── ingestion_service/        # Core ingestion logic
│   │   ├── core/                 # Ingestion engines
│   │   │   ├── pathway_sync.py   # Pathway CDC poller & MinIO monitor
│   │   │   ├── gdrive_sync.py    # Google Drive connector
│   │   │   ├── airbyte_connector.py # Airbyte integration
│   │   │   ├── universal_fanout.py  # 5-sink fanout orchestrator (Qdrant, OpenSearch, Neo4j, Postgres, Redis)
│   │   │   ├── pipeline_runner.py   # RAG pipeline execution
│   │   │   ├── sync_runner.py    # Source-to-pipeline sync orchestrator
│   │   │   ├── indexer.py        # Document chunking & embedding
│   │   │   └── page_yielder.py   # Document page extraction
│   │   ├── clients/              # External service clients
│   │   │   ├── scraper.py        # Web scraper client
│   │   │   └── source_sync.py    # Source connector orchestrator
│   │   ├── embeddings/           # Embedding clients
│   │   │   ├── client.py         # OpenAI, Cohere, NVIDIA embedding clients
│   │   │   └── sparse_client.py  # BM25 sparse embedding client
│   │   └── vector/               # Vector store operations
│   │       ├── qdrant_store.py   # Qdrant client & operations
│   │       ├── search.py         # Multi-strategy search (naive, semantic, hybrid)
│   │       ├── filters.py        # Qdrant filter builders
│   │       └── hit_mapper.py     # Search result transformation
│   └── file_manager/             # File operations
│       ├── core/                 # File service logic
│       │   ├── service.py        # File CRUD operations
│       │   ├── storage.py        # MinIO storage operations
│       │   ├── chunks.py         # Chunked upload handling
│       │   ├── duplicates.py     # Duplicate detection (SHA-256)
│       │   ├── operations.py     # File move/copy/delete
│       │   ├── validator.py      # File validation
│       │   └── errors.py         # Custom exceptions
│       └── utils/                # File utilities
│           ├── hashing.py        # SHA-256 hashing
│           └── paths.py          # Path sanitization & storage layout
├── alembic/                      # Database migrations
│   ├── versions/                 # Migration scripts
│   │   ├── 001_initial_schema.py
│   │   ├── 005_sources.py
│   │   ├── 007_multi_connector_sources.py
│   │   ├── 008_knowledge_store.py
│   │   └── 009_pipeline_knowledge_profile.py
│   └── env.py                    # Alembic environment config
├── storage/                      # Runtime storage
│   ├── ingestion.db             # SQLite database (204 KB)
│   ├── local_sources/           # Local file sources
│   ├── uploads/                 # Chunked upload temp storage
│   └── staging/                 # Processing temp storage
├── pyproject.toml               # Python dependencies (uv)
├── .env                         # Environment variables
└── Dockerfile                   # Container build
```

#### Key Database Models (`src/shared/db/models.py`)
1. **`Source`** — External data source (MinIO bucket + connectors)
   - Fields: `name`, `source_type`, `minio_bucket`, `connector_type`, `config`, `status`, `enabled`
   - Relationships: `connectors` (1:N), `pipeline_links` (M:N via `PipelineSource`)

2. **`SourceConnector`** — Airbyte/Pathway connector instance
   - Fields: `source_id`, `connector_type`, `config`, `status`, `sync_interval_minutes`
   - Types: `google_drive`, `s3`, `azure_blob`, `google_sheets`, `postgres`, `mysql`, `mongodb`, `web_scraper`, `confluence`, `sftp`

3. **`Pipeline`** — RAG ingestion pipeline
   - Fields: `name`, `description`, `collection_name`, `embedding_model`, `search_strategy`, `chunk_size`, `chunk_overlap`
   - Relationships: `sources` (M:N via `PipelineSource`), `runs` (1:N)

4. **`KnowledgeProfile`** — 5-sink fanout configuration
   - Fields: `name`, `description`, `enabled`, `status`, `error_message`, `last_sync_at`
   - Relationships: `sources` (M:N via `KnowledgeProfileSource`), `destinations` (1:N)

5. **`KnowledgeProfileDestination`** — Single destination sink
   - Fields: `profile_id`, `destination_type`, `enabled`, `config`, `status`, `last_sync_at`, `error_message`
   - Types: `vector_qdrant`, `lexical_opensearch`, `graph_neo4j`, `relational_pgvector`, `cache_redisvl`

#### API Endpoints (`apps/api/routes/`)
```
POST   /api/sources                     # Create new data source
GET    /api/sources                     # List all sources
GET    /api/sources/{id}                # Get source details
PUT    /api/sources/{id}                # Update source config
DELETE /api/sources/{id}                # Delete source
POST   /api/sources/{id}/sync           # Trigger manual sync
POST   /api/sources/{id}/connectors     # Add connector to source
DELETE /api/sources/{id}/connectors/{connector_id}  # Remove connector

GET    /api/knowledge-profiles          # List all knowledge profiles
POST   /api/knowledge-profiles          # Create new profile
GET    /api/knowledge-profiles/{id}     # Get profile details
PUT    /api/knowledge-profiles/{id}     # Update profile
DELETE /api/knowledge-profiles/{id}     # Delete profile
POST   /api/knowledge-profiles/{id}/sync # Trigger 5-sink fanout
POST   /api/knowledge-profiles/{id}/test-connection # Test destinations

GET    /api/pipelines                   # List all pipelines
POST   /api/pipelines                   # Create new pipeline
GET    /api/pipelines/{id}              # Get pipeline details
PUT    /api/pipelines/{id}              # Update pipeline
DELETE /api/pipelines/{id}              # Delete pipeline
POST   /api/pipelines/{id}/index        # Trigger pipeline indexing

GET    /api/files                       # List files
POST   /api/uploads                     # Chunked file upload
GET    /api/directories                 # List directories
POST   /api/directories                 # Create directory
```

#### 5-Sink Fanout Architecture (`universal_fanout.py`)
When a Knowledge Profile triggers sync, documents flow to 5 parallel destinations:

1. **`vector_qdrant`** — Dense vector embeddings (HNSW graph indexing)
   - Config: `collection_name`, `embedding_model`, `quantization`
   
2. **`lexical_opensearch`** — BM25 lexical inverted index
   - Config: `index_name`, `endpoint_url`, `analyzer`
   
3. **`graph_neo4j`** — Entity-relationship extraction for GraphRAG
   - Config: `bolt_uri`, `entity_extraction_model`, `relationship_types`
   
4. **`relational_pgvector`** — ACID-compliant metadata + vector embeddings
   - Config: `table_name`, `connection_string`, `vector_dimensions`
   
5. **`cache_redisvl`** — Parent-child chunk mapping + RAPTOR summaries
   - Config: `redis_url`, `index_prefix`, `ttl_seconds`

---

### Frontend Architecture (`rag-ingestion-manager/frontend/`)

#### Directory Structure
```
frontend/src/
├── pages/                        # Page components (16 total)
│   ├── HomePage.tsx             # Overview dashboard
│   ├── BrowsePage.tsx           # MinIO file browser
│   ├── SourcesPage.tsx          # Data sources list
│   ├── SourceDetailPage.tsx     # Source config & file upload
│   ├── KnowledgeStorePage.tsx   # 5-sink fanout manager
│   ├── PipelinesPage.tsx        # RAG pipeline CRUD
│   ├── TrackingPage.tsx         # Pipeline run history
│   ├── DirectoryPage.tsx        # Virtual folder view
│   ├── FileViewerPage.tsx       # File preview
│   ├── ChatPage.tsx             # (Integrated chat UI)
│   ├── PromptsPage.tsx          # (Prompt management)
│   ├── EvaluationsPage.tsx      # (RAG evaluation results)
│   ├── GoldenEvaluationsPage.tsx # (Golden dataset eval)
│   ├── GuardrailsConfigPage.tsx # (AI guardrails config)
│   ├── GuardrailsTracesPage.tsx # (Guardrails traces)
│   └── GuardrailsEvaluationPage.tsx # (Guardrails eval)
├── components/                   # Reusable components
│   ├── AppLayout.tsx            # Persistent SPA layout
│   ├── Icons.tsx                # SVG icon library
│   ├── StatusBadge.tsx          # Status indicator
│   ├── Breadcrumb.tsx           # Navigation breadcrumbs
│   ├── PageHeader.tsx           # Page title header
│   ├── MarkdownMessage.tsx      # Markdown renderer
│   └── Sources/                 # Source-specific components
│       ├── FileBrowser.tsx      # MinIO file browser UI
│       └── ConnectorConfigForm.tsx # Connector configuration form
├── utils/                        # Utility functions
│   └── format.ts                # Date/size formatters
├── api.ts                        # Backend API client (Axios)
├── App.tsx                       # React Router setup
├── main.tsx                      # React app entry point
├── index.css                     # Global styles (4863 lines)
└── vite-env.d.ts                # TypeScript types
```

#### Key Features
1. **Persistent SPA Layout** (`AppLayout.tsx`)
   - All pages remain mounted; only active page visible (`persistent-page--active`)
   - Preserves state during navigation (running pipelines, in-progress uploads, form fields)
   - CSS-based show/hide with fade-in animation

2. **Knowledge Store Manager** (`KnowledgeStorePage.tsx`)
   - Create/edit Knowledge Profiles
   - Link MinIO source buckets (M:N relationship)
   - Configure 5 destination engines (Qdrant, OpenSearch, Neo4j, Postgres, Redis)
   - Test connection for each destination (1.0s-1.5s timeout, schema validation fallback)
   - Trigger multi-sink fanout sync

3. **Sources Manager** (`SourcesPage.tsx`, `SourceDetailPage.tsx`)
   - Create MinIO-backed data sources
   - Add/remove Airbyte connectors (Google Drive, S3, Azure Blob, etc.)
   - Direct file upload via `FileBrowser.tsx` (chunked upload to MinIO)
   - Monitor connector sync status

4. **File Browser** (`BrowsePage.tsx`, `FileBrowser.tsx`)
   - Select MinIO source bucket from dropdown
   - List files with search/filter
   - Drag-and-drop file upload
   - File preview/download

---

## 2. RAG-RETRIEVAL-CHAT-MANAGER PROJECT

### Purpose
**Multi-strategy RAG chat, retrieval evaluation, AI guardrails, real-time monitoring**

### Backend Architecture (`rag-retrieval-chat-manager/backend/`)

#### Directory Structure
```
backend/
├── apps/                          # Multi-process applications
│   ├── rag-api/                   # FastAPI REST API server (port 8000)
│   │   └── src/rag_api/
│   │       ├── main.py           # FastAPI app with RAGPipeline, Retriever, Generator
│   │       ├── deps/             # Dependency injection
│   │       └── routes/           # API endpoints
│   │           ├── chat.py       # Chat session & message APIs
│   │           ├── retrieve.py   # Multi-strategy retrieval
│   │           ├── generate.py   # LLM generation (LiteLLM)
│   │           ├── search.py     # Vector search
│   │           ├── rerank.py     # Reranking (Cohere, NVIDIA)
│   │           ├── evaluate.py   # RAG evaluation (RAGAS)
│   │           ├── guardrails.py # AI guardrails CRUD
│   │           ├── guardrails_evaluate.py # Guardrails evaluation
│   │           ├── prompts.py    # System prompt overrides
│   │           ├── knowledge.py  # Knowledge profile integration
│   │           └── health.py     # Health check
│   └── eval-worker/               # Background evaluation worker (RQ)
│       └── src/eval_worker/
│           ├── main.py           # RQ worker process
│           └── tasks.py          # RAGAS evaluation tasks
├── libs/                          # Shared libraries (monorepo-style)
│   ├── shared/                   # Cross-cutting concerns
│   │   └── src/rag_shared/
│   │       ├── config.py         # Pydantic settings
│   │       ├── auth.py           # API key auth
│   │       ├── tracing.py        # OpenTelemetry tracing
│   │       ├── logging_config.py # Structured logging
│   │       ├── guardrails_client.py # Guardrails HTTP client
│   │       ├── chunk_utils.py    # Chunk text utilities
│   │       └── types.py          # Shared type definitions
│   ├── rag-core/                 # RAG pipeline orchestration
│   │   └── src/rag_core/
│   │       ├── pipeline.py       # RAGPipeline: retrieve → rerank → generate
│   │       ├── schemas.py        # Pydantic request/response models
│   │       └── prompts.py        # Default system prompts
│   ├── retrieval-core/           # Retrieval strategies
│   │   └── src/retrieval_core/
│   │       ├── retriever.py      # Multi-strategy retriever (naive, semantic, hybrid, HyDE, GraphRAG)
│   │       └── hit_mapper.py     # Search result transformation
│   ├── vector-core/              # Vector store operations
│   │   └── src/vector_core/
│   │       ├── qdrant_store.py   # Qdrant client
│   │       ├── search.py         # Vector search
│   │       ├── embedding_client.py # OpenAI/Cohere embeddings
│   │       ├── sparse_client.py  # BM25 sparse embeddings
│   │       ├── vision_client.py  # Multimodal embeddings
│   │       ├── filters.py        # Qdrant filters
│   │       └── hit_mapper.py     # Result mapping
│   ├── generation-core/          # LLM generation
│   │   └── src/generation_core/
│   │       ├── generator.py      # LiteLLM generator
│   │       ├── vision_generator.py # Multimodal generation
│   │       ├── prompt_builder.py # RAG prompt construction
│   │       ├── result.py         # Generation result model
│   │       └── prompts.py        # Default prompts
│   ├── reranker-core/            # Reranking strategies
│   │   └── src/reranker_core/
│   │       ├── base.py           # Reranker interface
│   │       ├── litellm_reranker.py # LiteLLM reranker (Cohere, NVIDIA)
│   │       └── noop.py           # No-op reranker
│   ├── eval-core/                # RAG evaluation
│   │   └── src/eval_core/
│   │       ├── runner.py         # Evaluation orchestrator
│   │       ├── ragas_client.py   # RAGAS metrics client
│   │       ├── retrieval_metrics.py # Precision, Recall, NDCG, MRR
│   │       ├── generation_metrics.py # Faithfulness, Answer Relevancy
│   │       ├── chat_metrics.py   # Chat-specific metrics
│   │       ├── rerank_metrics.py # Reranker evaluation
│   │       ├── dataset_schema.py # Golden dataset schema
│   │       ├── guardrails_runner.py # Guardrails evaluation
│   │       ├── guardrails_dataset_schema.py # Guardrails dataset
│   │       └── source_match.py   # Source citation matching
│   └── database/                 # PostgreSQL persistence
│       └── src/rag_db/
│           ├── models/           # SQLAlchemy models
│           │   ├── chat.py       # ChatSession, ChatMessage, ChatPipelineTrace, ChatMessageMetrics
│           │   ├── evaluation.py # EvaluationRun, EvaluationResult
│           │   └── guardrails.py # GuardrailsConfig, GuardrailsTrace, GuardrailsEvaluation
│           ├── repositories/     # Data access layer
│           │   ├── chat_repository.py
│           │   ├── evaluation_repository.py
│           │   └── guardrails_repository.py
│           ├── services/         # Database service
│           │   └── database.py   # AsyncSession factory
│           ├── migrate.py        # Alembic migration runner
│           └── sanitize.py       # SQL injection prevention
├── tests/                        # Unit & integration tests
│   ├── unit/                     # Unit tests (pytest)
│   │   ├── test_chat_metrics.py
│   │   ├── test_retrieval_metrics.py
│   │   ├── test_generator_no_sources.py
│   │   ├── test_reranker.py
│   │   ├── test_sparse_client.py
│   │   └── ...
│   └── integration/              # Integration tests
│       └── test_qdrant_retrieve.py
├── pyproject.toml               # Python dependencies (workspace)
└── .env                         # Environment variables
```

#### Key Database Models (`libs/database/src/rag_db/models/`)

**Chat Models** (`chat.py`):
1. **`ChatSession`** — Chat conversation session
   - Fields: `id`, `created_at`, `source_type`, `source_id`, `metadata_`
   - Relationships: `messages` (1:N)

2. **`ChatMessage`** — Single chat message
   - Fields: `id`, `session_id`, `role`, `content`, `created_at`
   - Relationships: `session`, `trace` (1:1), `metrics` (1:1)

3. **`ChatPipelineTrace`** — RAG pipeline execution trace
   - Fields: `message_id`, `pipeline_id`, `query`, `retrieved_docs`, `reranked_docs`, `final_answer`, `retrieval_time_ms`, `generation_time_ms`

4. **`ChatMessageMetrics`** — Per-message evaluation metrics
   - Fields: `message_id`, `faithfulness`, `answer_relevancy`, `context_precision`, `context_recall`

**Evaluation Models** (`evaluation.py`):
1. **`EvaluationRun`** — Batch evaluation run
   - Fields: `id`, `pipeline_id`, `dataset_name`, `status`, `started_at`, `completed_at`, `total_items`, `processed_items`

2. **`EvaluationResult`** — Single evaluation result
   - Fields: `run_id`, `question`, `expected_answer`, `actual_answer`, `faithfulness`, `answer_relevancy`, `retrieval_precision`, `retrieval_recall`

**Guardrails Models** (`guardrails.py`):
1. **`GuardrailsConfig`** — AI guardrails configuration
   - Fields: `id`, `name`, `description`, `rules`, `enabled`

2. **`GuardrailsTrace`** — Guardrails execution trace
   - Fields: `id`, `message_id`, `config_id`, `input_text`, `output_text`, `triggered_rules`, `blocked`

3. **`GuardrailsEvaluation`** — Guardrails evaluation result
   - Fields: `id`, `config_id`, `dataset_name`, `accuracy`, `precision`, `recall`, `f1_score`

#### API Endpoints (`apps/rag-api/src/rag_api/routes/`)
```
# Chat
POST   /api/chat/sessions           # Create chat session
GET    /api/chat/sessions           # List sessions
GET    /api/chat/sessions/{id}      # Get session history
POST   /api/chat/sessions/{id}/messages # Send message (RAG pipeline)
GET    /api/chat/messages/{id}/trace    # Get pipeline trace

# Retrieval
POST   /api/retrieve                # Multi-strategy retrieval
POST   /api/search                  # Vector search
POST   /api/rerank                  # Rerank results

# Generation
POST   /api/generate                # LLM generation

# Evaluation
POST   /api/evaluate                # Run RAGAS evaluation
GET    /api/evaluate/runs           # List evaluation runs
GET    /api/evaluate/runs/{id}      # Get run results

# Guardrails
GET    /api/guardrails              # List guardrails configs
POST   /api/guardrails              # Create config
POST   /api/guardrails/{id}/evaluate # Evaluate guardrails
GET    /api/guardrails/traces       # List traces

# Knowledge Integration
GET    /api/knowledge/profiles      # List Knowledge Profiles from ingestion-manager
POST   /api/knowledge/profiles/{id}/query # Query profile destinations

# Prompts
GET    /api/prompts                 # List system prompts
POST   /api/prompts                 # Override system prompt

# Health
GET    /api/health                  # Health check
```

#### RAG Pipeline Flow (`libs/rag-core/src/rag_core/pipeline.py`)
```
User Query
    ↓
1. RETRIEVE (retrieval-core)
   ├─ Naive: Direct vector search
   ├─ Semantic: Dense embeddings + cosine similarity
   ├─ Hybrid: Vector + BM25 weighted fusion
   ├─ HyDE: Hypothetical document embeddings
   ├─ Self-RAG: Iterative self-refinement
   ├─ CRAG: Corrective retrieval with web search fallback
   ├─ Adaptive: Dynamic strategy selection
   ├─ Agentic: Multi-step agent-driven retrieval
   ├─ GraphRAG: Neo4j community summaries + entity traversal
   └─ Multimodal: Vision embeddings for images
    ↓
2. RERANK (reranker-core)
   ├─ Cohere Rerank
   ├─ NVIDIA NeMo Reranker
   └─ No-op (skip reranking)
    ↓
3. GENERATE (generation-core)
   ├─ Build RAG prompt (system + context + query)
   ├─ LiteLLM generation (OpenAI, Anthropic, Google, etc.)
   ├─ Stream response chunks
   └─ Extract citations
    ↓
4. TRACE & METRICS
   ├─ Save ChatPipelineTrace (retrieved docs, timing)
   ├─ Calculate ChatMessageMetrics (RAGAS)
   └─ Check Guardrails (if enabled)
    ↓
Final Answer + Sources
```

---

### Frontend Architecture (`rag-retrieval-chat-manager/frontend/`)

#### Directory Structure
```
frontend/src/
├── pages/                        # Page components (17 total)
│   ├── HomePage.tsx             # Overview dashboard
│   ├── ChatPage.tsx             # RAG chat interface
│   ├── PromptsPage.tsx          # System prompt management
│   ├── EvaluationsPage.tsx      # RAG evaluation results
│   ├── GoldenEvaluationsPage.tsx # Golden dataset evaluation
│   ├── TrackingPage.tsx         # Chat trace history
│   ├── GuardrailsConfigPage.tsx # AI guardrails config
│   ├── GuardrailsTracesPage.tsx # Guardrails trace history
│   ├── GuardrailsEvaluationPage.tsx # Guardrails evaluation
│   ├── KnowledgeStorePage.tsx   # Knowledge Profile integration
│   ├── SourcesPage.tsx          # (Integrated sources list)
│   ├── SourceDetailPage.tsx     # (Integrated source config)
│   ├── PipelinesPage.tsx        # (Integrated pipeline CRUD)
│   ├── BrowsePage.tsx           # (Integrated file browser)
│   ├── DirectoryPage.tsx        # (Integrated folder view)
│   ├── FileViewerPage.tsx       # (Integrated file preview)
│   └── UploadPage.tsx           # (Integrated file upload)
├── components/                   # Reusable components
│   ├── AppLayout.tsx            # Persistent SPA layout
│   ├── Icons.tsx                # SVG icon library
│   ├── StatusBadge.tsx          # Status indicator
│   ├── Breadcrumb.tsx           # Navigation breadcrumbs
│   ├── PageHeader.tsx           # Page title header
│   ├── MarkdownMessage.tsx      # Markdown renderer (chat)
│   └── Sources/                 # Source-specific components
│       ├── FileBrowser.tsx      # MinIO file browser UI
│       └── ConnectorConfigForm.tsx # Connector configuration form
├── utils/                        # Utility functions
│   └── format.ts                # Date/size formatters
├── api.ts                        # Backend API client (Axios)
├── guardrailsEvalApi.ts         # Guardrails API client
├── App.tsx                       # React Router setup
├── main.tsx                      # React app entry point
├── index.css                     # Global styles
└── vite-env.d.ts                # TypeScript types
```

#### Key Features
1. **Chat Interface** (`ChatPage.tsx`)
   - Real-time chat with RAG-powered responses
   - Pipeline strategy selection (10 strategies)
   - Source citation display
   - Message trace inspection (retrieved docs, timing)
   - Streaming response support

2. **RAG Evaluation** (`EvaluationsPage.tsx`)
   - Upload golden dataset (CSV/JSON)
   - Run RAGAS evaluation (batch)
   - View metrics: Faithfulness, Answer Relevancy, Context Precision, Context Recall
   - Compare pipeline strategies

3. **AI Guardrails** (`GuardrailsConfigPage.tsx`, `GuardrailsTracesPage.tsx`)
   - Define guardrails rules (PII detection, toxicity, prompt injection)
   - View real-time guardrails traces
   - Evaluate guardrails accuracy

4. **Knowledge Integration** (`KnowledgeStorePage.tsx`)
   - Query Knowledge Profiles from `rag-ingestion-manager`
   - Route queries to specific destinations (Qdrant, OpenSearch, Neo4j, Postgres, Redis)
   - Multi-strategy retrieval across destinations

---

## SHARED ARCHITECTURE PATTERNS

### 1. Multi-Process Backend Architecture
Both projects use **3-process architecture**:
- **API Server** (FastAPI) — REST API, handles HTTP requests
- **Background Worker** (RQ) — Async job processing (file uploads, evaluations)
- **Real-time Worker** (Pathway/CDC) — Streaming data ingestion (ingestion-manager only)

### 2. Frontend SPA Pattern
Both frontends use **Persistent Page Layout**:
- All pages mounted at app startup (`PersistentPage` wrapper)
- Only active page visible (`persistent-page--active` CSS class)
- State preserved during navigation (no re-mounting)
- Smooth fade-in transitions (300ms)

### 3. Database Schema
**Ingestion-Manager (SQLite)**:
- 10 tables: `sources`, `source_connectors`, `pipelines`, `pipeline_sources`, `knowledge_profiles`, `knowledge_profile_sources`, `knowledge_profile_destinations`, `directories`, `files`, `sync_jobs`

**Retrieval-Manager (PostgreSQL)**:
- 8 tables: `chat_sessions`, `chat_messages`, `chat_pipeline_traces`, `chat_message_metrics`, `evaluation_runs`, `evaluation_results`, `guardrails_configs`, `guardrails_traces`, `guardrails_evaluations`

### 4. API Design Patterns
- **RESTful** endpoints with consistent naming
- **Async/await** throughout (FastAPI + SQLAlchemy AsyncSession)
- **Pydantic** for request/response validation
- **API key authentication** via header (`X-API-Key`)
- **CORS** enabled for local development
- **Structured error handling** with custom exceptions

### 5. Storage Architecture
**Ingestion-Manager**:
- **MinIO S3** — Document storage (isolated buckets per source)
- **SQLite** — Metadata, job queue
- **Qdrant** — Vector embeddings
- **OpenSearch** — BM25 lexical index
- **Neo4j** — GraphRAG knowledge graph
- **PostgreSQL** — Relational metadata + pgvector
- **Redis** — Cache + RAPTOR summaries

**Retrieval-Manager**:
- **PostgreSQL** — Chat history, traces, evaluations
- **Qdrant** — Vector search
- **Redis** — RQ job queue

---

## INTEGRATION POINTS

### 1. Knowledge Profile Integration
**Flow:** `rag-ingestion-manager` → `rag-retrieval-chat-manager`

1. User creates **Knowledge Profile** in ingestion-manager
2. Links MinIO source buckets (M:N)
3. Configures 5 destination engines (Qdrant, OpenSearch, Neo4j, Postgres, Redis)
4. Triggers fanout sync → documents indexed in all 5 destinations
5. Retrieval-manager queries Knowledge Profile destinations via API
6. Multi-strategy retrieval routes to appropriate destination:
   - **Naive/Semantic** → Qdrant (vector)
   - **Hybrid** → OpenSearch (BM25) + Qdrant (vector)
   - **GraphRAG** → Neo4j (entity traversal)
   - **Metadata** → PostgreSQL (relational queries)
   - **Adaptive** → Redis (cached summaries)

### 2. Shared Configuration
Both projects share:
- **Qdrant** connection (`QDRANT_URL`, `QDRANT_API_KEY`)
- **OpenAI** API key (`OPENAI_API_KEY`) for embeddings
- **MinIO** credentials (`MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`)
- **Redis** URL (`REDIS_URL`) for job queues

---

## DEPLOYMENT ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────────┐
│                     ENTERPRISE RAG PLATFORM                      │
└─────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────┐  ┌──────────────────────────────┐
│  RAG-INGESTION-MANAGER (Port 8007) │  │ RAG-RETRIEVAL-CHAT-MANAGER   │
│  ┌────────────────────────────┐  │  │ (Port 8000)                  │
│  │ FastAPI API Server         │  │  │ ┌─────────────────────────┐  │
│  │ - Sources CRUD             │  │  │ │ FastAPI API Server      │  │
│  │ - Knowledge Profile CRUD   │  │  │ │ - Chat Sessions         │  │
│  │ - Pipeline CRUD            │  │  │ │ - RAG Pipeline          │  │
│  │ - File Operations          │  │  │ │ - Evaluation            │  │
│  └────────────────────────────┘  │  │ │ - Guardrails            │  │
│  ┌────────────────────────────┐  │  │ └─────────────────────────┘  │
│  │ Pathway CDC Worker         │  │  │ ┌─────────────────────────┐  │
│  │ - MinIO monitoring         │  │  │ │ RQ Eval Worker          │  │
│  │ - Airbyte connectors       │  │  │ │ - RAGAS evaluation      │  │
│  └────────────────────────────┘  │  │ └─────────────────────────┘  │
│  ┌────────────────────────────┐  │  └──────────────────────────────┘
│  │ RQ Background Worker       │  │
│  │ - File uploads             │  │  ┌──────────────────────────────┐
│  │ - Pipeline indexing        │  │  │ Frontend (Port 5173)         │
│  └────────────────────────────┘  │  │ - React + TypeScript + Vite  │
└──────────────────────────────────┘  └──────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│                     STORAGE LAYER                                │
├──────────────────────────────────────────────────────────────────┤
│ MinIO S3 (Port 9000)      │ Qdrant (Port 6333)                   │
│ - Document storage        │ - Vector embeddings                  │
│ - Isolated buckets        │ - Dense retrieval                    │
├───────────────────────────┼──────────────────────────────────────┤
│ OpenSearch (Port 9200)    │ Neo4j (Port 7687)                    │
│ - BM25 lexical index      │ - GraphRAG knowledge graph           │
│ - Sparse retrieval        │ - Entity relationships               │
├───────────────────────────┼──────────────────────────────────────┤
│ PostgreSQL (Port 5432)    │ Redis (Port 6379)                    │
│ - Chat history            │ - Job queue (RQ)                     │
│ - Evaluation results      │ - Cache + RAPTOR summaries           │
│ - pgvector embeddings     │                                      │
└──────────────────────────────────────────────────────────────────┘
```

---

## TECHNOLOGY STACK

### Backend
- **Language:** Python 3.11+
- **Framework:** FastAPI 0.115+
- **ORM:** SQLAlchemy 2.0+ (AsyncSession)
- **Database:** SQLite (ingestion), PostgreSQL 16+ (retrieval)
- **Queue:** Redis + RQ (async jobs)
- **Migrations:** Alembic
- **Validation:** Pydantic v2
- **Embeddings:** OpenAI, Cohere, NVIDIA
- **LLM:** LiteLLM (OpenAI, Anthropic, Google, Azure, etc.)
- **Vector Store:** Qdrant
- **Search:** OpenSearch (BM25)
- **Graph:** Neo4j
- **Cache:** Redis (RedisVL)
- **Object Storage:** MinIO S3
- **CDC:** Pathway (Airbyte connectors)
- **Evaluation:** RAGAS

### Frontend
- **Language:** TypeScript 5.5+
- **Framework:** React 18+
- **Build Tool:** Vite 6.4+
- **Router:** React Router 7+
- **HTTP Client:** Axios
- **Styling:** CSS (custom variables, no framework)
- **Package Manager:** npm

### DevOps
- **Container:** Docker
- **Orchestration:** Docker Compose
- **Reverse Proxy:** (Not configured, direct port access)

---

## KEY ARCHITECTURAL DECISIONS

### 1. Why Two Separate Projects?
**Separation of Concerns:**
- **Ingestion** — Heavy I/O, long-running CDC streams, multi-sink fanout
- **Retrieval** — Low-latency, real-time chat, streaming responses
- Different scaling profiles (ingestion scales horizontally, retrieval scales vertically)

### 2. Why SQLite for Ingestion?
- Embedded database (no separate server)
- Sufficient for metadata & job queue
- Simplified deployment
- Can migrate to PostgreSQL if needed

### 3. Why PostgreSQL for Retrieval?
- ACID transactions for chat history
- pgvector extension for hybrid search
- Complex analytical queries for evaluation metrics
- Production-grade reliability

### 4. Why Persistent Page Layout?
- Preserves state during navigation (no re-mounting)
- Better UX for long-running operations (file uploads, pipeline runs)
- Reduces API calls (pages fetch data once, cache in memory)

### 5. Why 5-Sink Fanout?
- **Future-proof for 10 RAG strategies** (2026 edition)
- Each strategy needs different storage:
  - Naive/Semantic → Qdrant (vector)
  - Hybrid → OpenSearch (BM25) + Qdrant
  - GraphRAG → Neo4j (graph)
  - Metadata → PostgreSQL (relational)
  - Adaptive → Redis (cache)
- Parallel fanout maximizes throughput
- Isolated failures (one sink down doesn't block others)

---

## CURRENT STATUS (2026-09-11)

### Verified Working
✅ `rag-ingestion-manager` backend running on port 8007  
✅ `rag-ingestion-manager` frontend running on port 5173  
✅ All 5 destination engines tested and operational:
   - Qdrant (vector)
   - OpenSearch (lexical)
   - Neo4j (graph)
   - PostgreSQL (relational)
   - Redis (cache)  
✅ Knowledge Profile created with 2 MinIO sources  
✅ All frontend pages load cleanly without errors  
✅ API endpoints returning correct data  
✅ MinIO file upload functional  
✅ Source connector integration working  

### Pending Integration
⚠️ `rag-retrieval-chat-manager` backend not currently running  
⚠️ Knowledge Profile → Retrieval Manager integration incomplete  
⚠️ Multi-strategy retrieval routing to Knowledge Profile destinations  

---

## NEXT STEPS

1. **Start `rag-retrieval-chat-manager` backend** on port 8000
2. **Integrate Knowledge Profile API** in retrieval-manager routes
3. **Implement multi-strategy routing** to query appropriate destinations
4. **Test end-to-end RAG flow:** Ingest → Fanout → Retrieve → Generate
5. **Run RAGAS evaluation** across all 10 strategies
6. **Deploy guardrails** for production safety

---

**End of Analysis**
