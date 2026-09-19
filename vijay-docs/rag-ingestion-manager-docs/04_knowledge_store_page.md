# 04 — Knowledge Store Fanout & Multi-Sink Visualizer Page

**Last updated:** 2026-09-17

## 1. Executive Summary & Page Purpose
The **Knowledge Store Fanout Page** (`frontend/src/pages/KnowledgeStorePage.tsx`, route: `/knowledge-store`, sidebar label "Knowledge Store") is the multi-sink orchestration hub of the ingestion service. It binds data sources (MinIO buckets and local-filesystem folders) to up to **5 destination sinks**, triggers parallel fanout syncs implemented in `backend/src/ingestion_service/core/universal_fanout.py`, and inspects the stored data through one tabbed **Interactive Visualizer Modal**.

Backend API: FastAPI router `apps/api/routes/knowledge.py` with prefix `/api/knowledge-profiles` (service `rag-ingestion-manager`, published on host port `8007`; every route sits behind the shared `verify_api_key` dependency, which is a no-op unless `API_KEY` is configured).

Two behaviour notes that the UI labels do not make obvious:
- Fanout granularity is **one record per document page**, not per text chunk. `universal_fanout.py` imports only `iter_file_pages`; the recursive splitter `ingestion_service/utils/text_splitter.py:chunk_text()` is used exclusively by the pipeline indexer (`ingestion_service/core/indexer.py:137`), not by fanout.
- The page is a control plane: it never talks to Qdrant/OpenSearch/Neo4j/Postgres/Redis directly. Every action is an HTTP call to the ingestion API, which performs the fanout synchronously inside a FastAPI background task.

---

## 2. 5-Destination Universal Fanout Architecture

```
              +-----------------------------------------------+
              |  Linked sources (MinIO bucket / local folder) |
              +----------------------+------------------------+
                                     |
                                     v
              +-----------------------------------------------+
              | execute_universal_fanout_sync()               |
              |  - list objects, sha256 differential ADD/UPD/DEL
              |  - iter_file_pages() -> page-level records    |
              +----------------------+------------------------+
                                     |  asyncio.gather(return_exceptions=True)
      +---------------+--------------+--------------+---------------+
      v               v              v              v               v
 vector_qdrant  lexical_opensearch  graph_neo4j  relational_pgvector  cache_redisvl
```

`execute_universal_fanout_sync()` computes a SHA-256 per object, skips unchanged files, purges + re-indexes changed files, purges + deletes records for objects removed from the source, and fans out to every **enabled** destination with `asyncio.gather(..., return_exceptions=True)` — a failing sink is logged and skipped, the remaining sinks still complete (`universal_fanout.py:161-320`).

### Destination list (values returned by `GET /api/knowledge-profiles/destinations/options`)

| id | name | category |
|---|---|---|
| `vector_qdrant` | Qdrant | Vector Engine |
| `lexical_opensearch` | OpenSearch | Lexical & Sparse Search |
| `graph_neo4j` | Neo4j (GraphRAG) | Knowledge Graph Store |
| `relational_pgvector` | PostgreSQL (pgvector) | Multi-Model Relational DB |
| `cache_redisvl` | RedisVL | Semantic Cache & Summary Store |

### Sink details

1. **Qdrant Vector DB (`vector_qdrant`)** — dense HNSW similarity search.
   - Collection name default `knowledge_qdrant_collection`; collection is created with `enable_sparse=False` (dense vector only) and `vector_size` from config (default `2048`), falling back to the first embedding's length when unset (`universal_fanout.py:545-593`).
   - `platform_common/vector/qdrant_store.py:ensure_collection()` recreates the collection when the existing dense vector size differs from the requested size.
   - One point per non-empty page, point id = random UUID, payload = fanout payload, dense vector = `EmbeddingClient.embed_passage(page.text)`.
2. **OpenSearch Lexical (`lexical_opensearch`)** — BM25 document store.
   - Index name default `knowledge_lexical_index`; the index is `PUT` with `number_of_shards` (default `1`), `number_of_replicas` (default `0`) and `refresh_interval` (default `"1s"`). No custom analyzer/mapping is created; `bm25_k1`, `bm25_b` and `sparse_model` are written as document metadata only (`universal_fanout.py:594-637`).
   - Optional HTTP basic auth via `auth_type=basic` + `username`/`password`.
3. **Neo4j GraphRAG (`graph_neo4j`)** — document/chunk graph.
   - `MERGE (d:Document {file_key}) SET d.updated_at`, then per page `MERGE (c:Chunk {chunk_id: "<file_key>:<page_index>"}) SET c.page_index, c.text, c.content` (text truncated to 500 chars) and `MERGE (d)-[:CONTAINS_CHUNK]->(c)` (`universal_fanout.py:638-685`).
   - When `entity_extraction_enabled` is on, entities are extracted via LiteLLM chat completions (temperature 0, first 4000 chars, up to `max_entities_per_chunk`) and merged as `(:Entity {name})` with `(:Chunk)-[:MENTIONS]->(:Entity)`.
   - `community_reports_enabled` and `entity_resolution_mode` are stored in config but not consumed by the fanout writer.
4. **PostgreSQL / pgvector (`relational_pgvector`)** — relational chunk table.
   - Table default `knowledge_chunks` (optionally schema-qualified by `schema_name`). `CREATE TABLE IF NOT EXISTS` with columns `id SERIAL PRIMARY KEY, file_key TEXT, page_index INT, content TEXT`, plus `embedding vector(<vector_size|2048>)` when `store_embeddings` is true, plus `created_at TIMESTAMPTZ DEFAULT NOW()`; one `INSERT` per page (`universal_fanout.py:686-760`).
   - `index_algorithm` and `distance_op` are config metadata; no index is created by the fanout writer.
5. **RedisVL (`cache_redisvl`)** — per-page Redis JSON cache (no vector index is written).
   - Key `"<index_prefix>:<file_key>:<page_index>"` (prefix default `knowledge_cache`), value JSON `{content, file_key, page_index, similarity_threshold, embedding_model}`, expiry `ttl_seconds` (default `86400`).
   - With `parent_child_mapping` (default true) it also `SADD`s the key into `"<index_prefix>:<file_key>:children"` and writes `parent_key` into the payload.
   - With `raptor_summaries` it additionally writes a 3-bullet LiteLLM summary to `"<index_prefix>:<file_key>:summary"` (`universal_fanout.py:761-816`).

---

## 3. UI Layout & Visual Components

```
+-------------------------------------------------------------------------------------------+
|  Knowledge Store Manager                                                                  |
|  Universal Multi-Sink Fanout Engine — Route MinIO documents to 5 enterprise 2026 RAG ...  |
|                                          [ Refresh ]  [ + New Knowledge Profile ]         |
+-------------------------------------------------------------------------------------------+
|  Cards: [ Total Profiles ] [ Connected MinIO Buckets ] [ Active RAG Sinks ]               |
|         [ Fanout Engine Architecture: "5 Parallel Sinks" ]                                |
+-------------------------------------------------------------------------------------------+
|  Profile: <name>                                   Status: [ IDLE / SYNCING / SUCCESS ]   |
|  Linked MinIO Source Buckets (n):  [ bucket chips | "Local FS: <folder>" chips ]          |
|  Actions: [ Sync All Sinks ] [ Multi-Sink Visualizer ] [ edit icon ] [ delete icon ]      |
|                                                                                           |
|  Configured Destination Stores (Universal 2026 RAG Multi-Sink)                            |
|  +--------------------------+  +--------------------------+  +--------------------------+ |
|  | Qdrant          [ACTIVE] |  | OpenSearch      [ACTIVE] |  | Neo4j (GraphRAG) [ACTIVE] | |
|  | Dense vector similarity  |  | BM25 lexical indexing... |  | Document-chunk graph...   | |
|  | Collection: <name>       |  | Index: <name>            |  | URI: <bolt_uri>          | |
|  | [Test Link] [Inspect Store] | ...                                                   | |
|  +--------------------------+  +--------------------------+  +--------------------------+ |
|  Linked RAG Pipelines (n): pipeline cards + [Create / Manage Pipelines]                  |
+-------------------------------------------------------------------------------------------+
```

Metrics are computed client-side from the profile list: `Total Profiles` = number of profiles, `Connected MinIO Buckets` = distinct `minio_bucket` values across all linked sources, `Active RAG Sinks` = number of destination rows with `enabled = true`. The fourth card is static text ("5 Parallel Sinks").

Profile card per destination (`KnowledgeStorePage.tsx:637-775`):
- `ACTIVE` / `OFF` badge from `destinations[].enabled`; disabled cards are dimmed.
- Config snippet per type: Qdrant → `Collection: <collection_name>`, OpenSearch → `Index: <index_name>`, Neo4j → `URI: <bolt_uri>`, Postgres → `Table: <table_name>`, Redis → `Prefix: <index_prefix>`.
- `Test Link` button (disabled while a test runs and when the destination is `OFF`); on success the label `Connected` is shown, otherwise `Failed`.
- `Inspect Store` button, only rendered when the destination is enabled; opens the visualizer modal on that tab.

Linked sources are rendered as chips: MinIO sources show the bucket name, local-filesystem sources (`connector_type`/`source_type` = `local_filesystem` or bucket prefixed `local-`) show `Local FS: <folder_name>`. File counts are not displayed on this page.

The **Linked RAG Pipelines** block lists pipelines whose `knowledge_profile_id` points at the profile and shows `Collection`, `Strategy: <rag_strategy> (<chunk_size> / <chunk_overlap>)`, `Embedding`, an ACTIVE badge and a `Delete` button (calls `DELETE /api/pipelines/{id}`).

---

## 4. Profile Create / Edit Modal (typed destination schemas)

`KnowledgeStorePage.tsx:881-1215` renders a single modal for create (`POST /api/knowledge-profiles`) and edit (`PUT /api/knowledge-profiles/{id}`).

- Fields: **Profile Name** (required, 1–128 chars), **Profile enabled** checkbox (default true), **Description** textarea.
- Source selection: checkboxes over `GET /api/sources`; on create **every source is preselected**, on edit the linked `source_ids` are preselected. Local-FS sources are labelled `Local File System (storage/local_sources/<folder>)`, MinIO sources `MinIO Bucket (<bucket>)`.
- Destination blocks: one per item of `GET /destinations/options` in returned order, each with an **Enable Fanout** checkbox (default true on create) and, when enabled, the typed field grid from `components/DestinationConfigFields.tsx`.
- Initial config values are `{...option.default_config, ...existing.config}` so the API defaults are shown before saving; the payload always contains all 5 destinations.

`DestinationConfigFields.tsx` renders `option.fields` grouped by `field.group` (group header in uppercase), two columns per group:
- Types: `string` → text input, `number` → number input, `password` → password input, `boolean` → checkbox, `select` → `<select>` over `field.options`, `model` → `<select>` over the LiteLLM model list filtered by `field.model_kind` (falls back to the full list when the filtered list is empty, and to a free-text input when no models are available at all).
- `field.required` adds ` *` to the label; `field.description` renders as a hint under the input; `field.placeholder` fills the input placeholder.
- Fields with `advanced: true` are hidden until the per-destination **"Show advanced settings"** toggle is pressed. The toggle only appears for destinations that have at least one advanced field.
- `field.min` / `field.max` are returned by the API as advisory metadata; the form does not clamp or validate against them.
- `min`/`max`/models are not enforced server-side either: `merge_destination_config()` only fills defaults for keys the client left `null` or `""`.

### Field schemas and defaults per destination

`GET /api/knowledge-profiles/destinations/options` returns `id`, `name`, `category`, `description`, `default_config` and `fields`. Defaults are built from `Settings`, so environment variables (`.env`: `QDRANT_URL`, `DATABASE_URL`, `REDIS_URL`, `LITELLM_BASE_URL`, `OPENAI_API_KEY`, `EMBEDDING_MODEL`, `SPARSE_EMBEDDING_MODEL`) override the code defaults listed below.

**`vector_qdrant` — Qdrant** (`knowledge_destination_schemas.py:66-98`)

| key | label | type | group | default | flags |
|---|---|---|---|---|---|
| `litellm_base_url` | LiteLLM Base URL | string | LiteLLM | `http://host.docker.internal:4000` | placeholder = resolved base URL |
| `litellm_api_key` | LiteLLM API Key | password | LiteLLM | `sk-bot` | placeholder = resolved key |
| `embedding_model` | Embedding Model | model/embedding | Embeddings | `nvidia-embed-passage` | required |
| `url` | Qdrant URL | string | Connection | `http://qdrant:6333` (code default `http://localhost:6333`) | required |
| `api_key` | Qdrant API Key | password | Connection | `qdrant` | |
| `collection_name` | Collection Name | string | Collection | `knowledge_qdrant_collection` | required |
| `vector_size` | Vector Dimensions | number | Collection | `2048` | descriptions: auto-detected from model output when mismatched |
| `distance` | Distance Metric | select | Collection | `Cosine` | options `Cosine` / `Euclid` / `Dot` |
| `hnsw_m` | HNSW M | number | HNSW Tuning | `16` | advanced, min 4, max 64 |
| `hnsw_ef_construct` | HNSW ef_construct | number | HNSW Tuning | `100` | advanced, min 32, max 512 |
| `quantization` | Quantization | select | HNSW Tuning | `none` | advanced, options `none` / `int8_scalar` / `binary` |
| `on_disk_payload` | Store Payload On Disk | boolean | Collection | `true` | advanced |

`hnsw_m`, `hnsw_ef_construct`, `quantization`, `on_disk_payload` and `distance` are config-only in the fanout writer: `ensure_collection()` is called with the default HNSW/COSINE parameters and `enable_sparse=False`.

**`lexical_opensearch` — OpenSearch** (`knowledge_destination_schemas.py:99-130`)

| key | label | type | group | default | flags |
|---|---|---|---|---|---|
| `endpoint_url` | OpenSearch URL | string | Connection | `http://opensearch:9200` | required |
| `index_name` | Index Name | string | Index | `knowledge_lexical_index` | required |
| `auth_type` | Authentication | select | Connection | `none` | options `none` / `basic` |
| `username` | Username | string | Connection | `""` | advanced |
| `password` | Password | password | Connection | `""` | advanced |
| `sparse_model` | Sparse Model | model/sparse | Lexical | `Qdrant/bm25` | stored in index metadata |
| `bm25_k1` | BM25 k1 | number | BM25 Tuning | `1.2` | advanced |
| `bm25_b` | BM25 b | number | BM25 Tuning | `0.75` | advanced |
| `number_of_shards` | Shards | number | Index | `1` | advanced, min 1 |
| `number_of_replicas` | Replicas | number | Index | `0` | advanced, min 0 |
| `refresh_interval` | Refresh Interval | string | Index | `1s` | advanced, placeholder `1s` |

This is the only destination without LiteLLM fields.

**`graph_neo4j` — Neo4j (GraphRAG)** (`knowledge_destination_schemas.py:131-165`)

| key | label | type | group | default | flags |
|---|---|---|---|---|---|
| `litellm_base_url` | LiteLLM Base URL | string | LiteLLM | `http://host.docker.internal:4000` | |
| `litellm_api_key` | LiteLLM API Key | password | LiteLLM | `sk-bot` | |
| `bolt_uri` | Bolt URI | string | Connection | `bolt://neo4j:7687` | required |
| `http_url` | HTTP URL | string | Connection | `http://neo4j:7474` | used by inspect/visualizer APIs |
| `auth_disabled` | Disable Authentication | boolean | Connection | `true` | |
| `username` | Username | string | Connection | `neo4j` | |
| `password` | Password | password | Connection | `password` | |
| `database` | Database | string | Connection | `neo4j` | |
| `entity_extraction_enabled` | Enable Entity Extraction | boolean | GraphRAG | `false` | |
| `entity_extraction_model` | Entity Extraction Model | model/chat | GraphRAG | `gpt-4o-mini` | |
| `max_entities_per_chunk` | Max Entities / Chunk | number | GraphRAG | `10` | advanced, min 1, max 50 |
| `community_reports_enabled` | Community Reports | boolean | GraphRAG | `false` | advanced |
| `entity_resolution_mode` | Entity Resolution | select | GraphRAG | `exact_match` | advanced, options `exact_match` / `fuzzy` / `llm` |

**`relational_pgvector` — PostgreSQL (pgvector)** (`knowledge_destination_schemas.py:166-194`)

| key | label | type | group | default | flags |
|---|---|---|---|---|---|
| `litellm_base_url` | LiteLLM Base URL | string | LiteLLM | `http://host.docker.internal:4000` | |
| `litellm_api_key` | LiteLLM API Key | password | LiteLLM | `sk-bot` | |
| `connection_url` | PostgreSQL URL | string | Connection | `postgresql://ingestion:ingestion@postgres:5432/ingestion` (code default localhost) | required |
| `schema_name` | Schema | string | Table | `public` | non-`public` values are prefixed onto the table name |
| `table_name` | Table Name | string | Table | `knowledge_chunks` | required |
| `store_embeddings` | Store Embeddings | boolean | Vectors | `true` | adds the `embedding` column |
| `embedding_model` | Embedding Model | model/embedding | Vectors | `nvidia-embed-passage` | |
| `vector_size` | Vector Dimensions | number | Vectors | `2048` | `vector(<n>)` column width |
| `index_algorithm` | Index Algorithm | select | Vectors | `hnsw` | advanced, options `hnsw` / `ivfflat` / `none` |
| `distance_op` | Distance Operator | select | Vectors | `vector_cosine_ops` | advanced, options `vector_cosine_ops` / `vector_l2_ops` / `vector_ip_ops` |

**`cache_redisvl` — RedisVL** (`knowledge_destination_schemas.py:195-225`)

| key | label | type | group | default | flags |
|---|---|---|---|---|---|
| `litellm_base_url` | LiteLLM Base URL | string | LiteLLM | `http://host.docker.internal:4000` | |
| `litellm_api_key` | LiteLLM API Key | password | LiteLLM | `sk-bot` | |
| `redis_url` | Redis URL | string | Connection | `redis://redis:6379/0` (code default `redis://localhost:6379/0`) | required |
| `index_prefix` | Key Prefix | string | Cache | `knowledge_cache` | required |
| `ttl_seconds` | TTL (seconds) | number | Cache | `86400` | min 60 |
| `similarity_threshold` | Semantic Similarity Threshold | number | Cache | `0.85` | min 0, max 1 |
| `embedding_model` | Cache Embedding Model | model/embedding | Semantic Cache | `nvidia-embed-passage` | |
| `parent_child_mapping` | Parent-Child Mapping | boolean | Structure | `true` | writes `parent_key` + `children` set |
| `raptor_summaries` | RAPTOR Summaries | boolean | Summaries | `false` | writes a LiteLLM summary key |
| `summary_model` | Summary Model | model/chat | Summaries | `gpt-4o-mini` | |

### LiteLLM model picker

`GET /api/knowledge-profiles/config/litellm-models?model_kind=<all|embedding|chat|sparse>` (default `all`) calls `<litellm_base_url>/v1/models` with a 10 s timeout and `Authorization: Bearer <openai_api_key>` when set. Each returned model is classified by substring: `embed`/`embedding`/`nvidia-embed`/`bge`/`e5` → `embedding`; `bm25`/`sparse`/`splade` → `sparse`; otherwise `chat`, and filtered by `model_kind` (`knowledge.py:162-243`). Response: `{source: "litellm", litellm_base_url, models: [{id, kind}]}`.

When the proxy is unreachable the endpoint answers `{source: "fallback", litellm_base_url, models: [...], warning: "Could not reach LiteLLM proxy; showing environment defaults."}` with the env lists: embeddings = `unique_embedding_models` (`embedding_model`, `multimodal_embedding_model`, `text-embedding-3-small`, `text-embedding-3-large`), chat = `[embedding_model, "gpt-4o-mini", "gpt-4o"]`, sparse = `[sparse_embedding_model]`. The modal prints the warning line in amber; when no models are returned at all it prints a client-side warning and model fields degrade to free-text inputs.

---

## 5. Live Multi-Sink Visualizers

`components/visualizers/DestinationVisualizerModal.tsx` opens from **Multi-Sink Visualizer** (defaults to the Vector tab) or **Inspect Store** (that destination's tab). It renders 5 tabs with engine badges — Vector Search/Qdrant, Lexical BM25/OpenSearch, Knowledge Graph/Neo4j, Relational Chunks/PostgreSQL, Semantic Cache/RedisVL — a **Refresh Live Data** button, and calls `GET /api/knowledge-profiles/{id}/inspect/{destination_type}` on open and on every tab change. Each visualizer renders an error panel when the payload carries `error`.

1. **Vector Search (`VectorVisualizer.tsx`)** — stat cards: Collection, Total Vectors, Collection Status (`🟢 <status>`), Vector Dimensions (`<points[0].vector_len or 384>D Dense`). Left: a 500×320 SVG scatter labelled "2D UMAP / PCA Semantic Cluster Space" with a keyword filter over `payload.text` / `payload.file_key`; x/y come from the backend's cheap projection (sums of vector dimensions), not from a real PCA/UMAP run. Right: point inspector showing Point ID, File Source (`payload.file_key`), Page / Index (`payload.page_index`) and Chunk Text Content (`payload.text`). No zoom, drag or hover tooltips.
2. **Lexical BM25 (`LexicalVisualizer.tsx`)** — stat cards: OpenSearch Index, Total Documents, Lexical Algorithm (static text "BM25 Okapi Scoring"), Top Token Density (`<n> Keywords`). Left: term-frequency bars (top 25 terms from the backend); clicking a term fills the search box. Right: posted-document list with `Score: <score.toFixed(2)>` and a content preview that expands from 2 to 8 lines when selected; the search box filters the fetched page of documents client-side.
3. **Knowledge Graph (`GraphVisualizer.tsx`)** — stat cards: Total Nodes, Total Relationships, Graph Schema (static "Doc ➔ CONTAINS_CHUNK"), Engine Protocol (static "Bolt / Cypher 5.x"). Left: force-directed simulation (repulsion, link attraction, centre gravity, 80 animation frames) in a 500×320 SVG with a Document/Chunk colour legend; only Document and Chunk nodes exist in the payload. Right: Node Identifier, Node Type, Label and, for chunks, a 80-char Chunk Text Preview. No entity nodes, drag, zoom or Cypher panel.
4. **Relational Chunks (`RelationalVisualizer.tsx`)** — stat cards: Table Name, Total Table Rows, Storage Engine (static "PostgreSQL 16 + pgvector"), SQL Partitioning (static "Indexed by file_key"). Left: table of `ID`, `File Key`, `Page` (`P.<page_index>`), `Snippet` with a client-side search over content/file_key. Right: Primary Key ID, Page Index, File Path, Full Content.
5. **Semantic Cache (`CacheVisualizer.tsx`)** — stat cards: Cache Index Prefix, Cached Keys, Cache Hit Rate, Used Memory (falls back to `1.13M` client-side). Left: key list showing `Data Type` and TTL (`No Expiry` when TTL is `-1`). Right: Redis Key, Key Type, Time To Live and a **static** policy paragraph ("cosine similarity threshold ≥ 0.85 … sub-5ms"). No gauge, no prompt/response values and no similarity computation.

---

## 6. Backend APIs & Inspection Contracts

| Method | Endpoint | Description | Request / Response |
|---|---|---|---|
| `GET` | `/api/knowledge-profiles/destinations/options` | Destination types with typed fields and Docker-aware defaults | `list[{id, name, category, description, default_config, fields}]` |
| `GET` | `/api/knowledge-profiles/config/litellm-models` | LiteLLM `/v1/models` with env fallback | query `model_kind=all\|embedding\|chat\|sparse`; `{source, litellm_base_url, models[], warning?}` |
| `GET` | `/api/knowledge-profiles` | List profiles with linked sources, destination configs and pipelines | `list[KnowledgeProfile]` |
| `POST` | `/api/knowledge-profiles` | Create profile | body `{name (1-128, unique → 400), description?, enabled=true, source_ids[], destinations[{destination_type, enabled, config}]}` |
| `GET` | `/api/knowledge-profiles/{id}` | Fetch one profile | `KnowledgeProfile` / 404 |
| `PUT` | `/api/knowledge-profiles/{id}` | Update metadata, source links and destinations | body fields all optional; omitted `source_ids`/`destinations` are left untouched |
| `DELETE` | `/api/knowledge-profiles/{id}` | Delete profile and purge indexed artifacts of enabled destinations | `{status: "deleted", profile_id, purge_summary}` |
| `POST` | `/api/knowledge-profiles/{id}/test-connection` | Connectivity check for one destination | body `{destination_type, config}` → `{status: "success"\|"error", destination_type, message, details?}` |
| `POST` | `/api/knowledge-profiles/{id}/sync` | Queue the fanout sync as a background task | 400 when the profile is disabled; `{status: "syncing", profile_id, message}` |
| `GET` | `/api/knowledge-profiles/{id}/inspect/{destination_type}` | Live visualizer payload | see per-type payloads below |

Create/update details (`knowledge.py:244-413`):
- Destination payloads pass through `normalize_destination_payload()`, which **drops unknown `destination_type` values** and merges each config with its typed defaults (`knowledge.py:276-280`, `:371-383`).
- `merge_destination_config()` keeps a user value only when it is neither `null` nor `""`; empty strings fall back to the default, so a field cannot be blanked from the UI.
- Update upserts destinations by `destination_type`; a destination left out of the payload keeps its stored row (there is no API to delete a single destination — use `enabled: false`).

`test-connection` semantics (`knowledge.py:441-589`): Qdrant probes `GET {url}/collections` (1.5 s timeout, also trying `http://localhost:6333`) and, when unreachable, still returns `success` with "collection configuration schema validated"; OpenSearch probes the endpoint root (1 s, also trying `http://opensearch:9200`) and otherwise returns `success` with "schema validated"; Neo4j, Postgres and Redis return `success` after validating the config shape only — no driver connection is opened. Only an unknown `destination_type` returns `error`. The UI therefore shows `Connected` for syntactically valid but unreachable sinks.

`sync` semantics (`knowledge.py:590-623`): the route sets `profile.status = "syncing"`, clears `error_message`, adds `_background_fanout_sync` to FastAPI `BackgroundTasks` and returns immediately. The background task calls `execute_universal_fanout_sync()`, then sets `profile.status` to the returned fanout status (`"success"` in the normal and no-sources cases, `"error"` only when the profile row disappears), stamps `last_sync_at`, copies `error_message` when present and stamps every enabled destination `status = "synced"` with `last_sync_at`. An exception inside the background task is logged only, so the profile would remain stuck on `"syncing"`.

### Inspection payloads (`knowledge.py:624-842`)

| destination_type | Source query | Payload |
|---|---|---|
| `vector_qdrant` | `GET /collections/{coll}`; `POST /collections/{coll}/points/scroll` with `limit: 50, with_payload: true, with_vector: true` | `collection_name`, `total_points` (`points_count`), `status`, `points[]` = `{id, x, y, z, payload, vector_len}` where `x/y/z` are sums of `vec[:10]`/`[10:20]`/`[20:30]`; on failure `{error, points: []}` |
| `lexical_opensearch` | `POST {url}/{index}/_search` `{"size": 30, "query": {"match_all": {}}}` | `index_name`, `total_docs`, `terms[]` (top 25 `<text,value>` from words >3 chars in each hit, first 40 words per hit), `documents[]` = `{id, file_key, page_index, content, score}` |
| `graph_neo4j` | `POST {http_url}/db/neo4j/tx/commit` with `MATCH (d:Document) OPTIONAL MATCH (d)-[r:CONTAINS_CHUNK]->(c:Chunk) RETURN d.file_key, c.chunk_id, c.page_index, substring(c.text,0,80) LIMIT 60`; basic auth header skipped when `neo4j_auth_disabled` | `nodes[]` = `{id, label, type: Document\|Chunk, color, snippet?}`, `links[]` = `{source, target, label: "CONTAINS_CHUNK"}`, `total_nodes`, `total_edges`. The database name in the URL is hard-coded `neo4j`; the `database` config field is not used here |
| `relational_pgvector` | `SELECT id, file_key, page_index, content, created_at FROM {schema.table} ORDER BY id DESC LIMIT 50` + `SELECT count(*)` | `table_name`, `total_rows`, `rows[]` = `{id, file_key, page_index, content, created_at}` |
| `cache_redisvl` | `KEYS {prefix}:*`, first 30 keys with `TTL`/`TYPE`, `INFO memory` | `prefix`, `total_cached_keys`, `used_memory_human`, `keys[]` = `{key, ttl, type}`, `cache_hit_rate` **hard-coded to 0.88** |
| anything else | — | `{destination_type, message: "Visualizer not implemented for this type"}` |

Pagination: nothing is paginated — Qdrant 50 points, OpenSearch 30 documents, Neo4j 60 rows, Postgres 50 rows, Redis 30 of the matched keys (totals are reported separately).

---

## 7. Profile Lifecycle, Fanout Payload & Purge

### Fanout payload (`_build_fanout_payload`, `universal_fanout.py:125-149`)

| Field | Value |
|---|---|
| `source_type` | `"file_ingest"` (`ingestion_service/types.py:2`) |
| `source_id` | UUID of the linked `Source` |
| `source_locator` / `file_key` | object key, e.g. `resumes/resume_alex.pdf` |
| `file_name` / `original_name` / `title` | basename of the key |
| `page_index` / `chunk_index` | both equal the page index (no chunker) |
| `type` | `"text"` |
| `content` / `text` | stripped page text |
| `knowledge_profile_id` | owning profile UUID |
| `created_at` | UTC ISO timestamp |

Per-sink projection of that payload:
- **Qdrant** — full payload + random `point_id` + dense embedding.
- **OpenSearch** — `file_key`, `page_index`, `content`, `text`, `source_id`, `source_locator`, `created_at` + `sparse_model`, `bm25_k1`, `bm25_b`.
- **Neo4j** — graph properties only: `Document.file_key`/`updated_at`, `Chunk.chunk_id`/`page_index`/`text` (500 chars, also copied to `content`), optional `Entity.name`.
- **PostgreSQL** — `file_key`, `page_index`, `content` (+ `embedding` when enabled).
- **Redis** — JSON `{content, file_key, page_index, similarity_threshold, embedding_model}` (+ `parent_key`), plus the `children` set and optional `summary` key.

### Sync (differential state)

`execute_universal_fanout_sync()` returns `{status, files_processed, files_added, files_updated, files_deleted, pages_processed, destinations_synced}`; with no linked sources it returns the same shape with zeros and `message: "No linked MinIO source buckets to sync."`. `files_processed` counts files that yielded at least one page, and `destinations_synced` collects each destination type that returned without raising. Local-filesystem sources are read from `storage/local_sources/<folder_name>`; MinIO sources are listed with `list_objects`.

### Purge-on-delete

`DELETE /api/knowledge-profiles/{id}` calls `purge_knowledge_profile()` (`universal_fanout.py:385-410`), which iterates the profile's linked sources, loads their `IndexedFile` rows, purges each `file_key` from every **enabled** destination and deletes the tracking rows. Destinations that are disabled are skipped, and their data is **not** removed. The response is `{purged_files, source_ids, destinations}`. The same `purge_file_from_destinations()` runs before re-indexing a changed file and when a file disappears from a source.

| Sink | Purge operation (`_sync_purge_file_from_destination`) |
|---|---|
| Qdrant | `delete` with filter `FieldCondition(key="file_key", match=MatchValue(file_key))` on the configured collection |
| OpenSearch | `POST /{index}/_delete_by_query` with `bool.should` of `term {file_key.keyword}` and `match_phrase {file_key}` |
| Neo4j | `MATCH (d:Document {file_key}) OPTIONAL MATCH (d)-[:CONTAINS_CHUNK]->(c) DETACH DELETE d, c`, then `MATCH (c:Chunk) WHERE c.chunk_id STARTS WITH "<file_key>:" DETACH DELETE c` |
| PostgreSQL | `DELETE FROM {schema.table} WHERE file_key = %s` (falls back from the configured URL to `settings.database_url`) |
| Redis | `KEYS *<file_key>*` then `DELETE` of the matched keys (glob is over the whole key space, not restricted to `index_prefix`) |

Each purge is wrapped in its own try/except and logs a warning per sink, so one unavailable store never blocks the others.

### Verification

`backend/scripts/e2e_knowledge_fanout.py` (run against `http://localhost:8007`) inspects all five destinations, deletes the profile, checks each store directly, recreates the profile with the 5 destination configs, clears `indexed_files` to force a re-sync, triggers `POST /sync`, polls `GET /api/knowledge-profiles/{id}` until the status leaves `syncing`, and re-inspects all five destinations.
