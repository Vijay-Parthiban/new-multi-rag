# 02 — RAG Pipelines Management Page

**Last updated:** 2026-09-20

## 1. Executive Summary & Page Purpose
The **Pipelines page** (`frontend/src/pages/PipelinesPage.tsx`, route `/pipelines`) creates and inspects pipeline records. Each record owns its Qdrant collection, dense embedding engine, optional sparse engine, chunking parameters, folder / MinIO-source scope, optional web scraper configuration, and an optional Knowledge Product link (the selector is labelled `Knowledge Product`).

Key facts:

- The page talks **only to the ingestion manager**, not the retrieval API: `API_URL = VITE_API_URL ?? "http://localhost:8007"` and requests carry `X-API-Key` only when `VITE_API_KEY` is set (`frontend/src/api.ts:3,16-18,52`).
- Select options are fetched at runtime from `GET /api/pipelines/options` — they are **not** hard-coded in the page (`PipelinesPage.tsx:15,68,302-346`).
- Every input field on this page is an **ingestion** knob. Reranker model, generator model, retrieve limit, top-k and hybrid fusion are **not** configurable here; they are backend settings (see §2) plus per-query overrides in the chat toolbar (doc 03).
- The pipeline `description` is unique and is what chat users select a pipeline by, not the UUID (`PipelinesPage.tsx:286-299`).

`GET /api/pipelines/options` returns (`rag-ingestion-manager/backend/apps/api/routes/pipelines.py:133-152`):

| Key | Values |
|---|---|
| `rag_strategies` | `naive` (Standard), `sparse` (Keyword), `hybrid` (Advanced Hybrid), `multimodal` (Visual & Text), `metadata` (Advanced Metadata) |
| `modalities` | `text` (Text), `image` (Visual) |
| `suggested_embedding_models` | ingestion `Settings.unique_embedding_models` (`src/shared/config/settings.py:59-77`) |
| `suggested_sparse_models` | `[Settings.sparse_embedding_model]` |
| `scraper_modes` | `httpx`, `playwright`, `auto` (`routes/pipelines.py:20`) |
| `collection_naming_hint` | free-text placeholder for the collection field |

---

## 2. Pipeline Topology & Stage Configuration (retrieval side)

The records created on this page are consumed by the retrieval service through `RAGPipeline` (`rag-retrieval-chat-manager/backend/libs/rag-core/src/rag_core/pipeline.py:14-145`). The real stage topology is:

```
+-------------------------------------------------------------------------------------------+
|  1. Query -> RAGPipeline.retrieve()                                                       |
|     mode = retrieval_mode (default hybrid), limit = retrieve_limit (default 20)           |
+---------------------------------------+---------------------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------------------+
|  2. Retrieval (Retriever.retrieve -> vector_core.search_scrape_chunks)                    |
|     - Dense: LiteLLM embeddings, input_type="query" (default model nvidia-embed-passage)  |
|       written to Qdrant named vector "dense", COSINE                                      |
|     - Sparse: FastEmbed SparseTextEmbedding (default Qdrant/bm25) -> Qdrant named vector  |
|       "sparse" (IDF modifier)                                                             |
|     - Hybrid: Qdrant query_points with two prefetch legs (limit * 2 each) fused by        |
|       FusionQuery(Fusion.RRF) — no alpha / weighted score blend anywhere in the code      |
|     - Filters: source_type all|web_scrape|file_ingest, optional source_id                 |
+---------------------------------------+---------------------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------------------+
|  3. Rerank (build_reranker)                                                               |
|     - rerank_enabled = false -> NoopReranker: keeps retrieval order, truncates to top_k,  |
|       rerank_score = retrieval_score                                                      |
|     - rerank_enabled = true  -> LiteLLMReranker: POST {litellm_base_url}/v1/rerank,       |
|       default model nvidia-rerank; `top_n` is sent only for non-NVIDIA/Nemotron models;   |
|       image chunks are sent as {"text","image"} passages when the model is a VL reranker  |
|     - Result: top_k chunks reordered by rerank_score (default top_k = 5)                  |
+---------------------------------------+---------------------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------------------+
|  4. Generation (Generator.generate)                                                       |
|     - split_chunks(): text chunks -> chat model, image chunks -> vision model             |
|     - both present -> a third call to the fusion model merges the two partial answers     |
+---------------------------------------+---------------------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------------------+
|  5. Guardrails + tracing — NOT inside the pipeline: routes/chat.py runs the guardrail     |
|     check on the query before and on the answer after the pipeline call                   |
+-------------------------------------------------------------------------------------------+
```

Verified defaults:

| Parameter | Default | Source |
|---|---|---|
| `retrieval_mode` | `hybrid` | `rag_core/schemas.py:9,28` |
| `retrieve_limit` | `20` (request-validated 1–50) | `rag_core/schemas.py:10,29` |
| `rerank_enabled` | `true` | `rag_core/schemas.py:11,30` |
| `top_k` | `5` (request-validated 1–50) | `rag_core/schemas.py:13,31` |
| dense embedding model | `nvidia-embed-passage` | `rag_shared/config.py:27` |
| sparse embedding model | `Qdrant/bm25` | `rag_shared/config.py:28` |
| reranker model | `nvidia-rerank` (`DEFAULT_RERANKER_MODEL`) | `rag_shared/config.py:33`, `reranker_core/litellm_reranker.py:15` |
| chat model | `llama-3.3-70b-versatile` | `rag_shared/config.py:36` |
| vision model | `groq-vision` | `rag_shared/config.py:37` |
| fusion model | `llama-3.3-70b-versatile` | `rag_shared/config.py:38` |
| chunk size / overlap | `1000` / `120` (bounds 100–8000 / 0–2000) | `routes/pipelines.py:31-32`, `PipelinesPage.tsx:55-56,432-455` |

Fusion detail: hybrid search issues `qmodels.Prefetch` for the dense and the sparse named vector with `limit=max(limit * 2, limit)` and fuses them with `qmodels.FusionQuery(fusion=qmodels.Fusion.RRF)` (`shared-libs/platform-common/src/platform_common/vector/qdrant_store.py:226-241`). If Qdrant rejects the sparse leg (400 mentioning `sparse`), hybrid falls back to dense-only search and logs a warning (`qdrant_store.py:245-258`). There is **no** alpha/weighted combination, no minimum relevance-score threshold, and no OpenSearch/SPLADE component in this service.

---

## 3. UI Layout & Visual Components

```
+-------------------------------------------------------------------------------------------------+
|  Pipelines                                                                                      |
|  Each pipeline has its own Qdrant collection, embedding models, and a unique description for    |
|  chat selection.                                                                                |
|  [ Trigger Sync* ] [ Refresh stats* ] [ Refresh pipelines ] [ View tracking ]                   |
|  (* only shown while a pipeline is selected)                                                    |
+-------------------------------------------------------------------------------------------------+
|  +--------------------------------------+  +--------------------------------------------------+ |
|  | New pipeline                         |  | Saved pipelines                                  | |
|  |  Internal name                       |  |  <description>                                   | |
|  |  Description (unique - used in chat) |  |  <name> · <rag_strategy>                         | |
|  |  Search Strategy                     |  |  <qdrant_collection>                             | |
|  |  Knowledge Product (if any exist)   |  |  <embedding_model>[ + <sparse_model>]            | |
|  |  Primary Text Engine                 |  |  [ Run ] [ Delete ]                              | |
|  |  Keyword Search Engine (sparse only) |  |                                                  | |
|  |  Content Type (multimodal/metadata)  |  |  Pipeline Details & Stats (selected pipeline)    | |
|  |  Folders to index []                 |  |   Indexed Files / Scraped Pages                  | |
|  |  MinIO Sources to link []            |  |   Config: Search Strategy / Processing Engines / | |
|  |  Document processing size / Overlap  |  |           Collection / Processing Size           | |
|  |  Qdrant collection                   |  |  Recent Activity: Status, Files, Pages, Points,  | |
|  |  [ ] Enable web scraper              |  |           Scraper (crawl job id prefix)          | |
|  |      Seed URL / Max depth / Max pages|  |                                                  | |
|  |      Scraper embedding source / Mode |  |                                                  | |
|  |  [ Save pipeline ]                   |  |                                                  | |
|  +--------------------------------------+  +--------------------------------------------------+ |
+-------------------------------------------------------------------------------------------------+
```

Behaviour notes:

- There is **no** `+ New Pipeline` button: the creation form is always rendered next to the list (`PipelinesPage.tsx:271-561`). Header actions are `Trigger Sync`, `Refresh stats`, `Refresh pipelines` and a `View tracking` link (`PipelinesPage.tsx:227-258`).
- Which fields are shown depends on the strategy: `Keyword Search Engine` for `sparse | hybrid | metadata`, `Content Type` for `multimodal | metadata` (`PipelinesPage.tsx:29-30,207-208`; rendered at `349-381`).
- Save is enabled only when: name non-empty, description ≥ 8 chars, embedding model chosen, collection ≥ 3 chars, sparse model chosen when required, and at least one folder **or** linked MinIO source **or** the web scraper is enabled (`PipelinesPage.tsx:209-215`).
- The form omits `sparse_embedding_model` (null) and `modality` (null) when the strategy does not need them; the web scraper's "Scraper embedding source" radio (`markdown`/`image`) supplies `modality` when the scraper is on and the strategy has no modality field (`PipelinesPage.tsx:133-152,516-542`).
- After a successful create, the page links every checked MinIO source to the new pipeline via `POST /api/sources/{sourceId}/pipeline/{pipelineId}` (`PipelinesPage.tsx:169-176`, `api.ts:1199-1209`).
- Selecting a pipeline loads its runs and stats and then re-polls both every **15000 ms**, only while `location.pathname === "/pipelines"` (`PipelinesPage.tsx:103,112-116`).
- Per-pipeline buttons are only `Run` and `Delete` (`PipelinesPage.tsx:584-620`). `test run`, `edit config` and `view analytics` actions do not exist in the page.
- `Recent Activity` renders `status`, `files_processed/files_total`, `pages_indexed`, `points_upserted`, and the first 8 characters of `scraper_crawl_job_id`; the newest run's `error_message` is shown as an error alert (`PipelinesPage.tsx:692-736`).

---

## 4. Backend APIs & Contracts

### 4.1 Ingestion manager endpoints used by the page

Base URL `API_URL` (default `http://localhost:8007`); router prefix `/api/pipelines` (`routes/pipelines.py:18`).

| Method | Endpoint | Description | Request / Response |
|---|---|---|---|
| `GET` | `/api/pipelines/options` | Strategy, modality, engine, scraper-mode lists | `{}` → options object (§1) |
| `GET` | `/api/pipelines` | Lists all pipelines, newest first | `list[PipelineRecord]` |
| `POST` | `/api/pipelines` | Creates a pipeline (201) | `PipelineCreateRequest` → `PipelineRecord` |
| `GET` | `/api/pipelines/{id}` | Single pipeline | `PipelineRecord` |
| `PATCH` | `/api/pipelines/{id}` | Updates directory list / scraper fields only | `PipelinePatchRequest` → `PipelineRecord` |
| `DELETE` | `/api/pipelines/{id}` | Deletes the pipeline (204) | – |
| `GET` | `/api/pipelines/{id}/stats` | `{indexed_files_count, scraped_pages_count}` | `PipelineStats` |
| `GET` | `/api/pipelines/{id}/runs` | Runs for one pipeline, newest first | `list[PipelineRunRecord]` |
| `POST` | `/api/pipelines/{id}/run` | Enqueues an ingestion run (202); 409 if a run is already pending/processing | → `PipelineRunRecord` |
| `POST` | `/api/pipelines/{id}/sync` | Pipeline directory file-sync (202), unrelated to Knowledge Products; requires `directory_names`, 409 if a run is active | → `{"status": "queued", "pipeline_id": "..."}` |
| `GET` | `/api/directories` | Folder checklist source | `list[DirectorySummary]` |
| `GET` | `/api/sources` | MinIO source checklist | `list[SourceRecord]` |
| `GET` | `/api/knowledge-products` | Knowledge Product selector | `list[KnowledgeProduct]` |

The page calls `listKnowledgeProducts`, `createPipeline`, `deletePipeline`, `startPipelineRun`, `listPipelineRuns`, `getPipelineStats`, `triggerPipelineSync`. `PATCH /api/pipelines/{id}` (`updatePipeline`) exists in the client but is not used by this page.

`PipelineRecord` keys: `id`, `knowledge_product_id`, `name`, `description`, `rag_strategy`, `embedding_model`, `sparse_embedding_model`, `modality`, `directory_names`, `chunk_size`, `chunk_overlap`, `qdrant_collection`, `web_scraper_enabled`, `scraper_seed_url`, `scraper_max_depth`, `scraper_max_pages`, `scraper_mode`, `created_at`, `updated_at` (built by `_pipeline_to_dict` in `routes/pipelines.py`).
`PipelineRunRecord` keys: `id`, `pipeline_id`, `status`, `files_total`, `files_processed`, `pages_indexed`, `points_upserted`, `scraper_crawl_job_id`, `scraper_scrape_job_id`, `error_message`, `started_at`, `completed_at`, `created_at` (`routes/pipelines.py:95-110`).

Server-side creation rules (`routes/pipelines.py:113-131`):

- `rag_strategy` ∈ `naive | sparse | hybrid | multimodal | metadata`; `modality` required for `multimodal | metadata`.
- `sparse_embedding_model` required for `sparse | hybrid`.
- At least one `directory_names` entry or `web_scraper_enabled = true`, otherwise `NO_SOURCES`.
- `scraper_seed_url` required when the web scraper is enabled.
- If `knowledge_product_id` is omitted, `POST /api/pipelines` attaches the oldest Knowledge Product; `GET /api/pipelines` backfills the same link on any unlinked record.

Note the asymmetry with the UI gate: the page also accepts "only MinIO sources selected" as a valid submission (`PipelinesPage.tsx:215`), but the API still rejects that request with `NO_SOURCES` because it checks folders and the scraper only.

### 4.2 Sample creation payload (`POST /api/pipelines`)

```json
{
  "name": "legal-docs-v1",
  "description": "Legal contract hybrid RAG for M&A due diligence",
  "rag_strategy": "hybrid",
  "embedding_model": "nvidia-embed-passage",
  "sparse_embedding_model": "Qdrant/bm25",
  "modality": null,
  "directory_names": ["contracts"],
  "chunk_size": 1000,
  "chunk_overlap": 120,
  "qdrant_collection": "legal-docs-hybrid-v1",
  "web_scraper_enabled": false,
  "scraper_seed_url": null,
  "scraper_max_depth": 2,
  "scraper_max_pages": 50,
  "scraper_mode": "httpx",
  "knowledge_product_id": "3695cb61-e728-4bf1-91f8-cf249d593c6b"
}
```

### 4.3 Retrieval-stage endpoints the configured pipeline maps onto

Served by the retrieval API (`rag-api`), all behind `Depends(verify_api_key)` (`rag_api/main.py:62`); the frontend client uses `RAG_API_URL = VITE_RAG_API_URL ?? "http://localhost:8001"` (`api.ts:5`).

| Method | Endpoint | Description | Request / Response |
|---|---|---|---|
| `GET` | `/search` | Retrieval only, query in the query string | `query_text` (required), `limit` (default 5, 1–50), `mode` (default `hybrid`), `source_type` (default `all`), `source_id` → `list[SearchResultResponse]` |
| `POST` | `/scrapes/query` | Retrieval only, JSON body | `{text_query, limit = 5, mode = "hybrid", source_type = "all", source_id}` → `list[RAGChunkItem]` |
| `POST` | `/retrieve` | Deprecated alias of `/scrapes/query` | `{text_query \| query, limit, mode \| retrieval_mode, source_type, source_id}` → `list[RAGChunkItem]` |
| `POST` | `/rerank` | Retrieve + rerank | `PipelineRequest` → `{retrieved_chunks, reranked_chunks, latency_ms}` |
| `POST` | `/generate` | Retrieve + rerank + generate | `PipelineRequest` → `{answer, sources[{source_locator, chunk_index, rerank_score}], latency_ms}` |
| `POST` | `/chat` | Full RAG turn with persistence | `ChatRequest` → `ChatResponse` (doc 03) |

Chunk keys returned by `/search`, `/scrapes/query` and `/retrieve`: `id`, `score`, `type` (`text` | `image`), `content`, `source_type`, `source_id`, `source_locator`, `chunk_index`, `source_url`, `title`, `scrape_job_id` (`routes/search.py:41-53`).

`PipelineRequest` keys (shared by `/rerank`, `/generate`, `/chat`, `/chat/stream`) (`rag_core/schemas.py:22-38`): `query` (required), `source_type`, `source_id`, `retrieval_mode` (`hybrid` | `dense` | `sparse`, default `hybrid`), `retrieve_limit` (default `20`, 1–50), `rerank_enabled` (default `true`), `rerank_model` (LiteLLM rerank alias, default `nvidia-rerank`), `top_k` (default `5`, 1–50), `generation_model`, `vision_model`, `fusion_model`, `collection`, `embedding_model`, `sparse_embedding_model`.

`latency_ms` keys returned by `/rerank`: `retrieve`, `rerank`, `total`. By `/generate` and `/chat`: plus `generate_text` / `generate_vision` / `generate_fusion` when those stages ran, `generate_total`, and `generate` (`pipeline.py:66-72,102-119`, `generator.py:112-143`).
