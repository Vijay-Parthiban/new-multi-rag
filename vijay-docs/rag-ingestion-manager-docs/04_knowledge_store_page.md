# 04 — Knowledge Products (Fanout & Multi-Sink Visualizer)

**Last updated:** 2026-09-20

## 1. Executive Summary & Page Purpose

The **Knowledge Store** area (`frontend/src/pages/KnowledgeStorePage.tsx`, route `/knowledge-store`) manages
**Knowledge Products**. A Knowledge Product links one or more MinIO source buckets to one or more ingestion
destinations and syncs them continuously.

- **List page** (`/knowledge-store`): one card per product, plus create and edit.
- **Product page** (`/knowledge-store/:id`, `frontend/src/pages/KnowledgeProductPage.tsx`): the product's own
  dashboard — live fanout timeline, destination cards, and the ingested-file ledger.

Clicking a card body opens the product page. The action buttons on the card handle their own clicks and do not
navigate.

Backend API: FastAPI router `apps/api/routes/knowledge_products.py`, prefix `/api/knowledge-products`
(service `rag-ingestion-manager`, host port `8007`; every route sits behind the shared `verify_api_key`
dependency, a no-op unless `API_KEY` is configured).

Two behaviour notes the UI labels do not make obvious:

- Fanout granularity is **one record per document page**, not per text chunk. `universal_fanout.py` imports only
  `iter_file_pages`; the recursive splitter `ingestion_service/utils/text_splitter.py:chunk_text()` belongs to the
  pipeline indexer only.
- The pages are a control plane. They never talk to Qdrant/OpenSearch/Postgres/Redis directly. Every action is an
  HTTP call to the ingestion API or a Server-Sent Events stream from it.

**There is no manual sync.** The product poller owns the schedule, and a sync also runs when a linked source
changes (see §7).

---

## 2. Four-Destination Fanout Architecture

```
              +-----------------------------------------------+
              |  Linked sources (MinIO bucket / local folder) |
              +----------------------+------------------------+
                                     |
                                     v
              +-----------------------------------------------+
              | execute_universal_fanout_sync(db, product)     |
              |  - list objects with etag + size               |
              |  - download only when a destination needs it   |
              |  - iter_file_pages() -> page-level records     |
              +----------------------+------------------------+
                                     |  asyncio.gather(return_exceptions=True)
        +----------------+-----------+-----------+----------------+
        v                v                       v                v
 vector_qdrant   lexical_opensearch   relational_pgvector   cache_redisvl
```

`execute_universal_fanout_sync()` compares each object's **etag and size** with the stored ledger row. An
unchanged file that already reached every enabled destination is skipped without a download. A changed file is
purged from the destinations that hold it and re-indexed. An object that left the bucket is purged from every
destination that held it and its ledger row is deleted.

Destination writes are parallel: one `asyncio.gather(..., return_exceptions=True)` per file over the destinations
that still need it. A failing destination is recorded as a failure and the others still complete.

### Destination list (`GET /api/knowledge-products/destinations/options`)

| id | name | category | namespace field |
|---|---|---|---|
| `vector_qdrant` | Qdrant | Vector Engine | `collection_name` |
| `lexical_opensearch` | OpenSearch | Lexical & Sparse Search | `index_name` |
| `relational_pgvector` | PostgreSQL (pgvector) | Multi-Model Relational DB | `schema_name` |
| `cache_redisvl` | RedisVL | Semantic Cache & Summary Store | `index_prefix` |

`graph_neo4j` was removed. Migration `010_knowledge_products` deletes the stored rows, and
`backend/scripts/purge_neo4j_legacy.py` removes the graph nodes those rows pointed at.

Each catalogue entry also carries `namespace_fields`, the list of config keys that identify its store. The API
uses that list to derive store names and to detect a clash between products, so adding a destination needs no
change to the isolation logic.

### Sink details

1. **Qdrant Vector DB (`vector_qdrant`)** — dense HNSW similarity search.
   - The collection is created with `enable_sparse=False` and `vector_size` from config (default `2048`), falling
     back to the first embedding's length.
   - One point per non-empty page, point id = random UUID, payload = the fanout payload, dense vector =
     `EmbeddingClient.embed_passage(page.text)`.
   - Purge matches on both `file_key` **and** `source_id`, so two sources holding the same key cannot purge each
     other.
2. **OpenSearch Lexical (`lexical_opensearch`)** — BM25 document store.
   - The index is `PUT` with `number_of_shards` (default `1`), `number_of_replicas` (default `0`) and
     `refresh_interval` (default `"1s"`). No custom analyzer is created; `bm25_k1`, `bm25_b` and `sparse_model`
     are document metadata only.
   - Purge uses `_delete_by_query` with `file_key.keyword`/`match_phrase` **and** `source_id.keyword`. The
     `.keyword` subfield is required: both fields are dynamically mapped as `text`, and a term query against the
     analysed field matches nothing.
3. **PostgreSQL / pgvector (`relational_pgvector`)** — one table per product.
   - The product's schema is created with `CREATE SCHEMA IF NOT EXISTS`, and the table is `chunks` inside it:
     `id SERIAL PRIMARY KEY, file_key TEXT, source_id TEXT, page_index INT, content TEXT`, plus
     `embedding vector(<vector_size|2048>)` when `store_embeddings` is true, plus
     `created_at TIMESTAMPTZ DEFAULT NOW()`.
   - `CREATE EXTENSION IF NOT EXISTS vector` runs before the table, so the destination works on a fresh database.
     The image must ship the extension; `docker-compose.yaml` uses `pgvector/pgvector:pg16`.
   - `ALTER TABLE ... ADD COLUMN IF NOT EXISTS source_id` and `CREATE INDEX IF NOT EXISTS` upgrade a table made
     by an older version.
   - Purge and inspect both use the same connection resolver as the writer (`pg_connection_urls`,
     `connect_pg`), which drops non-Postgres candidates. Without that the dev SQLite default would be handed to
     psycopg.
4. **RedisVL (`cache_redisvl`)** — per-page Redis JSON cache.
   - Page key `"<index_prefix>:<source_id>:<file_key>:<page_index>"`, value JSON
     `{content, file_key, source_id, page_index, similarity_threshold, embedding_model}`,
     expiry `ttl_seconds` (default `86400`).
   - With `parent_child_mapping` it also `SADD`s the key into `"<index_prefix>:<source_id>:<file_key>:children"`
     and writes `parent_key` into the payload.
   - With `raptor_summaries` it writes a 3-bullet LiteLLM summary to `"<prefix>:<source_id>:<file_key>:summary"`.
   - Purge scans `"<prefix>:<source_id>:<file_key>*"` with Redis glob metacharacters escaped, instead of the old
     whole-database `KEYS *<file_key>*`.

---

## 3. Per-Product Store Isolation

Every product writes to its own stores. The names come from the product name and id:

```
slug   = slugify_product_name(name)       # "My Res!" -> "my_res", max 32 chars, fallback "product"
suffix = product_id.hex[:8]
```

| destination | derived store name |
|---|---|
| `vector_qdrant` | `collection_name = kp_<slug>_<suffix>` |
| `lexical_opensearch` | `index_name = kp_<slug>_<suffix>` |
| `relational_pgvector` | `schema_name = kp_<slug>_<suffix>` (table stays `chunks`) |
| `cache_redisvl` | `index_prefix = kp:<slug>:<suffix>` |

`apply_store_namespace(destination_type, config, slug, suffix, settings)` replaces a value that is empty or still
equal to the catalogue default. A value the user typed is kept, so a custom store name survives every re-save.
Because the table name is fixed and the schema carries the identity, two products may share a table name.

**A clash is rejected.** `_validate_store_namespace` compares each incoming namespace value against every other
product's stored config and answers `422` with:

```json
{"detail": {"code": "DESTINATION_STORE_CONFLICT", "message": "…",
            "field": "collection_name", "value": "kp_a_1f2a3dcf",
            "destination_type": "vector_qdrant", "conflicting_product": "Product A"}}
```

Two products over the same bucket are safe. They index the same objects into separate stores, and the
per-product ledger (§5) means one product's records never make another skip a file.

---

## 4. UI Layout & Visual Components

### List page

```
+---------------------------------------------------------------------------------+
|  Knowledge Store Manager                                                        |
|  Universal Multi-Sink Fanout Engine — Route MinIO documents to 4 enterprise ...  |
|                                        [ Refresh ]  [ Create Knowledge Product ] |
+---------------------------------------------------------------------------------+
|  Cards: [ Total Products ] [ Connected MinIO Buckets ] [ Active RAG Sinks ]      |
|         [ Fanout Engine Architecture: "4 Parallel Sinks" ]                       |
+---------------------------------------------------------------------------------+
|  <product name>  [STATUS]  [LIVE POLLING | Scheduled every 30s]                  |
|  Linked MinIO Source Buckets (n): [bucket chips]                                 |
|  Actions: [ Pause All | Resume All ] [ edit ] [ delete ]                         |
|                                                                                 |
|  Configured Destination Stores                                                   |
|  +-----------------------+  +-----------------------+  +----------------------+  |
|  | Qdrant       [ACTIVE] |  | OpenSearch   [ACTIVE] |  | ...                  |  |
|  | <collection_name>     |  | <index_name>          |  |                      |  |
|  | [Test Link]           |  | [Test Link]           |  |                      |  |
|  +-----------------------+  +-----------------------+  +----------------------+  |
|  Linked RAG Pipelines (n): pipeline cards + [Create / Manage Pipelines]          |
+---------------------------------------------------------------------------------+
```

Metrics are computed client-side: `Total Products`, `Connected MinIO Buckets` = distinct `minio_bucket` values,
`Active RAG Sinks` = destination rows with `enabled = true`. The fourth card is static text "4 Parallel Sinks".

The whole card is the click target for `/knowledge-store/<id>` and is keyboard reachable (`role="button"`,
`tabIndex=0`, Enter/Space). Each action button stops propagation, so a button click never navigates.

Card action buttons: **Pause All** / **Resume All** (label follows
`destinations.every(d => !d.enabled)`), edit, and delete. The delete button opens `ConfirmDialog` with the source
count, the destination count and the indexed-file count; there is no browser `confirm()`.

The store-name snippet is derived from the option's own `namespace_fields`, with `relational_pgvector` shown as
`schema.table`. No destination id is hardcoded in the card.

### Product page

```
Overview > Knowledge Store > <name>
<h1> <name>  [STATUS]  [Live polling | Scheduled every 30s]   [← Back] [Pause All Destinations]
[ Source Buckets ] [ Files Indexed ] [ Pages Indexed ] [ Last Sync ]      (stats cards)
Live Fanout:  MinIO bucket → Parse & chunk → <one chip per enabled destination>
              Added / Updated / Deleted / Unchanged / Pages  + Live|Reconnecting dot
              scrolling event log (last 30 events)
Destination Stores (n enabled):  one card per destination
              <name> [Enabled|Paused] · <store name> · Last sync · error
              [ Pause | Resume ] [ Inspect Store ] [ Configure ]
Ingested Files:  table of File Key / Source / Status / Pages / Destinations / Updated
```

The page polls `GET /api/knowledge-products/{id}` and `/{id}/files` every 5 seconds — 5 s rather than 20 s so the
page still feels live when the SSE stream is reconnecting.

- **Pause All Destinations** / **Resume All Destinations**: one `POST` to `pause-all` or `resume-all`.
- **Pause** / **Resume** per destination: `PATCH /{id}/destinations/{destination_id}`.
- **Inspect Store**: opens the visualizer on that destination's tab.
- **Configure**: edits that destination's config and saves through `PATCH /{id}` with the full destination list,
  so the other destinations are sent back unchanged.
- No sync button exists anywhere.

---

## 5. The Ledger and Live Events

### `knowledge_product_files`

One row per `(product, source, file_key)`, unique on that triple. This replaces the `indexed_files` rows the
fanout used to write, and it is what makes two products over one bucket independent.

| column | meaning |
|---|---|
| `file_key`, `source_id` | which object in which bucket |
| `etag`, `size_bytes` | the metadata fingerprint used for change detection |
| `content_hash` | SHA-256 of the downloaded bytes |
| `status` | `pending`, `syncing`, `synced`, `failed` |
| `pages_indexed` | page count of the last successful parse |
| `destinations_synced` | JSON list of destination types that currently hold this file |
| `error_message`, `last_synced_at` | last failure text and last success time |

A file is `synced` once it reaches **every enabled** destination. A destination that is paused is not in that
set, so `destinations_synced` lists exactly the stores that hold the content. `GET /{id}/files` returns these
rows with the bucket name joined in, newest change first, `limit` capped at 200.

### Events (`src/ingestion_service/core/knowledge_events.py`)

An in-process bus with a replay buffer of the last 200 events per product. `GET /{id}/events` streams them as
Server-Sent Events.

| kind | fields |
|---|---|
| `tick_start` | — |
| `file_start` | `source_id`, `file_key`, `change` (`added` \| `updated` \| `resynced`) |
| `destination_start` | `file_key`, `destination_type` |
| `destination_done` | `file_key`, `destination_type`, `pages` |
| `destination_failed` | `file_key`, `destination_type`, `error` |
| `file_synced` | `source_id`, `file_key`, `pages` |
| `file_deleted` | `source_id`, `file_key` |
| `file_failed` | `source_id`, `file_key`, `error` |
| `tick_done` | `files_added`, `files_updated`, `files_deleted`, `files_unchanged`, `pages`, `destinations` |

Every event carries `seq` and `ts`. The stream sends `: keepalive\n\n` every 15 s so a proxy does not close it.
The frontend uses `fetch` + `ReadableStream` rather than `EventSource`, because `EventSource` cannot send the
`X-API-Key` header (`frontend/src/hooks/useProductEvents.ts`, keeps the last 300 events, retries after 3 s).

`LiveFanoutTimeline.tsx` derives everything from that stream: the destination chips, the current file, the
counters from the last `tick_done`, and the event log. Nothing is polled separately, so the panel and the backend
cannot disagree.

---

## 6. Create / Edit Modal

One modal for create (`POST /api/knowledge-products`) and edit (`PATCH /api/knowledge-products/{id}`).

- **Product Name** (required, 1–128 chars, unique → 400), **Product enabled** checkbox, **Description**.
- **Sync Mode**: a radio pair, **Immediate live sync** / **Scheduled sync**. Live hides the interval row. Scheduled
  shows a number input plus a unit select, `Seconds (minimum 5)` or `Minutes`.
- **Link Data Sources**: checkboxes over `GET /api/sources`; on create every source is preselected. Local-FS
  sources are labelled `Local File System (storage/local_sources/<folder>)`, MinIO sources
  `MinIO Bucket (<bucket>)`.
- **Configure Destination Stores**: one block per catalogue entry, each with an **Enable Fanout** checkbox and, when
  enabled, the typed field grid from `components/DestinationConfigFields.tsx`.
- Initial config values are `{...option.default_config, ...existing.config}`, so the store-name fields start at
  the catalogue default and the API re-derives the per-product name on save.

Client-side validation: a name is required, at least one source, and at least one enabled destination.

Server-side schedule rules (`_apply_schedule`):

- `live` clears both intervals.
- `scheduled` with `sync_interval_seconds` clears minutes, and the reverse.
- `scheduled` with neither, on a product that has no stored interval, raises `422 INTERVAL_REQUIRED`.
- `scheduled` with neither, on a product that already has one, keeps the stored value.

`DestinationConfigFields.tsx` is generic over `option.fields` and needs no change when a destination is added.
It renders `field.group` as uppercase headers, hides `advanced: true` fields behind a per-destination
"Show advanced settings" toggle, and maps `string`/`number`/`password`/`boolean`/`select`/`model` to inputs.
`model` fields list the LiteLLM models filtered by `field.model_kind`, fall back to the full list when the filter
is empty, and degrade to a free-text input when no models load.

`field.min` / `field.max` are advisory metadata; neither the form nor `merge_destination_config()` clamps them.

### Field schemas and defaults per destination

Defaults are built from `Settings`, so `.env` overrides the code defaults. `merge_destination_config()` keeps a
user value only when it is neither `null` nor `""`.

**`vector_qdrant`** — LiteLLM fields, `embedding_model` (model/embedding, required), `url` (required),
`api_key`, `collection_name` (required, **namespace field**), `vector_size` (default `2048`), `distance`,
`hnsw_m`, `hnsw_ef_construct`, `quantization`, `on_disk_payload` (last four advanced).

**`lexical_opensearch`** — `endpoint_url` (required), `index_name` (required, **namespace field**), `auth_type`,
`username`/`password` (advanced), `sparse_model`, `bm25_k1`, `bm25_b`, `number_of_shards`,
`number_of_replicas`, `refresh_interval`. The only destination without LiteLLM fields.

**`relational_pgvector`** — LiteLLM fields, `connection_url` (required), `schema_name` (**namespace field**),
`table_name` (default `chunks`), `store_embeddings`, `embedding_model`, `vector_size`, `index_algorithm`,
`distance_op`.

**`cache_redisvl`** — LiteLLM fields, `redis_url` (required), `index_prefix` (required, **namespace field**),
`ttl_seconds`, `similarity_threshold`, `embedding_model`, `parent_child_mapping`, `raptor_summaries`,
`summary_model`.

### LiteLLM model picker

`GET /api/knowledge-products/config/litellm-models?model_kind=<all|embedding|chat|sparse>` calls
`<litellm_base_url>/v1/models` with a 10 s timeout and `Authorization: Bearer <openai_api_key>` when set. Models
are classified by substring: `embed`/`embedding`/`nvidia-embed`/`bge`/`e5` → `embedding`;
`bm25`/`sparse`/`splade` → `sparse`; otherwise `chat`. When the proxy is unreachable the endpoint answers
`source: "fallback"` with the environment lists and a warning the modal shows in amber.

---

## 7. Scheduling, Source Reactivity and Purge

### The product poller (`src/ingestion_service/core/knowledge_sync.py`)

One `asyncio` task per enabled product, started at app startup by `init_all_knowledge_pollers()` and re-registered
by `register_knowledge_poller(product_id)` after every create, edit, pause and destination toggle.

`resolved_interval_seconds(product)`:

| condition | interval |
|---|---|
| `monitor_mode == live` | `3` s |
| `sync_interval_seconds` set | `max(5, value)` |
| `sync_interval_minutes` set | `max(5, value * 60)` |
| neither | `300` s |

`register_knowledge_poller` stops the old task, re-reads the product, and returns early — logging
`knowledge_poller_skipped` with a reason — when the product is missing, disabled, has no linked source, or has
every destination paused. Otherwise it stores the new task and fires one immediate sync, so a new product starts
ingesting at once.

`sync_knowledge_product(product_id)` guards on an in-process `_SYNCING_PRODUCTS` set, so a burst of source events
collapses into one running fanout. It sets `status = "syncing"`, calls the fanout, then sets `status = "idle"`,
`last_sync_at`, clears `error_message` and stamps every enabled destination.

A product with **every destination paused stops polling**. It therefore does not notice new bucket objects while
paused; resume restarts the poller and the next tick picks them up. A single paused destination does not stop the
poller — the other destinations keep receiving files, and the paused one catches up when it is resumed.

### Source reactivity

`_trigger_pipeline_syncs(db, source)` in `pathway_sync.py` no longer runs the fanout. It looks up the products
linked to the source and starts `sync_knowledge_product` for each as a fire-and-forget task, then enqueues the
pipeline runs as before. This keeps a manual upload or a delete reflected in the destinations within seconds
rather than at the next poll interval, without the fanout running twice.

`apps/api/routes/sources.py:_trigger_sync_in_background` calls it with the corrected argument order
`(db_session, db_source)`.

### Purge

`purge_knowledge_product(db, product)` walks the ledger, purges each file from exactly the destinations listed in
`destinations_synced` — including paused ones, because a paused store must not keep deleted content — and deletes
the ledger rows. `DELETE /{id}` then removes the product (cascading to its sources, destinations and files),
stops the poller and clears the product's event history.

`purge_file_from_destinations(product, source_id, file_key, destination_types=None)` is the shared entry point.
With `destination_types=None` it purges every enabled destination.

### Fanout payload (`_build_fanout_payload`)

| Field | Value |
|---|---|
| `source_type` | `"file_ingest"` |
| `source_id` | UUID of the linked `Source` |
| `source_locator` / `file_key` | object key, e.g. `resumes/resume_alex.pdf` |
| `file_name` / `original_name` / `title` | basename of the key |
| `page_index` / `chunk_index` | both equal the page index (no chunker) |
| `type` | `"text"` |
| `content` / `text` | stripped page text |
| `knowledge_product_id` | owning product UUID |
| `created_at` | UTC ISO timestamp |

Per-sink projection: **Qdrant** the full payload plus the embedding; **OpenSearch** `file_key`, `page_index`,
`content`, `text`, `source_id`, `source_locator`, `created_at` plus `sparse_model`, `bm25_k1`, `bm25_b`;
**PostgreSQL** `file_key`, `source_id`, `page_index`, `content` (+ `embedding`); **Redis** the JSON value plus the
`children` set and the optional `summary`.

### Return value

`execute_universal_fanout_sync()` returns `{status, files_processed, files_added, files_updated, files_deleted,
files_unchanged, pages_processed, destinations_synced}`. With no linked sources it returns the same shape with
zeros and `message: "No linked MinIO source buckets to sync."`; with no enabled destination, the same with
`message: "No destination is enabled."`.

---

## 8. Backend APIs

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/knowledge-products/destinations/options` | destination types with typed fields, defaults and `namespace_fields` |
| `GET` | `/api/knowledge-products/config/litellm-models` | LiteLLM `/v1/models` with env fallback |
| `GET` | `/api/knowledge-products` | list products with counters |
| `POST` | `/api/knowledge-products` | create; starts ingestion; `201` |
| `GET` | `/api/knowledge-products/{id}/files` | ledger rows; `?status=&limit=50&offset=0` |
| `GET` | `/api/knowledge-products/{id}/events` | SSE fanout stream |
| `GET` | `/api/knowledge-products/{id}` | one product |
| `PATCH` | `/api/knowledge-products/{id}` | partial update of fields, sources and destinations |
| `DELETE` | `/api/knowledge-products/{id}` | purge every destination, then delete |
| `PATCH` | `/api/knowledge-products/{id}/destinations/{destination_id}` | body `{enabled}` — pause or resume one destination |
| `POST` | `/api/knowledge-products/{id}/pause-all` | pause every destination in one update |
| `POST` | `/api/knowledge-products/{id}/resume-all` | resume every destination in one update |
| `POST` | `/api/knowledge-products/{id}/test-connection` | connectivity check for one destination |
| `GET` | `/api/knowledge-products/{id}/inspect/{destination_type}` | visualizer payload |

Routes are declared literal-first, so `/destinations/options` and `/config/litellm-models` precede
`/{product_id}`. `PUT` was replaced by `PATCH`, matching `/api/sources/{id}`.

**Removed:** `POST /{id}/sync` and `_background_fanout_sync`. A `POST` to `/{id}/sync` now returns `404`.

Create/update details:

- Destination payloads pass through `normalize_destination_payload()`, which **drops unknown `destination_type`
  values** and merges each config with its typed defaults, then through `apply_store_namespace()`.
- Creating links the sources, writes the destinations, and calls `register_knowledge_poller()` — which performs the
  first sync. No second call is needed.
- `PATCH` **deletes destination rows whose type is absent from the payload**. Unchecking a destination in the UI
  therefore stops it instead of leaving it running.
- `PATCH` calls `await db.refresh(product)` before serialising, because `updated_at` carries `onupdate=func.now()`
  and reading it without a refresh raises `MissingGreenlet`.
- `pause-all`, `resume-all` and a destination toggle each perform one commit and then **one**
  `register_knowledge_poller` call. The UI must not loop individual `PATCH`es, which would race on re-registration.

`test-connection` semantics: Qdrant probes `GET {url}/collections` (1.5 s, also trying `http://localhost:6333`);
OpenSearch probes the endpoint root (1 s, also trying `http://opensearch:9200`); Postgres and Redis validate the
config shape only. Only an unknown `destination_type` returns `error`, so the UI shows `Connected` for a
syntactically valid but unreachable sink.

### Inspection payloads

| destination_type | Source query | Payload |
|---|---|---|
| `vector_qdrant` | `GET /collections/{coll}`; `POST .../points/scroll` `{limit: 50, with_payload: true, with_vector: true}` | `collection_name`, `total_points`, `status`, `points[] = {id, x, y, z, payload, vector_len}`; `x/y/z` are sums of `vec[:10]`/`[10:20]`/`[20:30]` |
| `lexical_opensearch` | `POST {url}/{index}/_search` `{size: 30, query: {match_all: {}}}` | `index_name`, `total_docs`, `terms[]` (top 25 from words > 3 chars), `documents[] = {id, file_key, page_index, content, score}` |
| `relational_pgvector` | `SELECT id, file_key, page_index, content, created_at FROM {schema}.chunks ORDER BY id DESC LIMIT 50` + `count(*)` | `table_name` (qualified), `schema_name`, `total_rows`, `rows[]` |
| `cache_redisvl` | `KEYS {prefix}:*`, first 30 keys with `TTL`/`TYPE`, `INFO memory` | `prefix`, `total_cached_keys`, `used_memory_human`, `keys[] = {key, ttl, type}` |

The Postgres branch uses the qualified `schema.chunks` name and the same connection resolver as the writer, so
inspect reads the store the fanout wrote. The fake `cache_hit_rate: 0.88` field was removed; the Redis panel now
shows the count of keys with a TTL, derived from the returned keys.

Pagination: nothing is paginated — 50 Qdrant points, 30 OpenSearch documents, 50 Postgres rows, 30 of the matched
Redis keys (totals reported separately).

---

## 9. Frontend Structure

| File | Role |
|---|---|
| `pages/KnowledgeStorePage.tsx` | list page: cards, pause-all, monitor badge, create/edit modal, delete dialog |
| `pages/KnowledgeProductPage.tsx` | product page: stats, live timeline, destination cards, files table |
| `components/knowledge/LiveFanoutTimeline.tsx` | the live pipeline panel, derived from the event stream |
| `hooks/useProductEvents.ts` | SSE client over `fetch` + `ReadableStream` |
| `components/visualizers/index.ts` | `VISUALIZERS` registry and `visualizerFor(type)` |
| `components/visualizers/DestinationVisualizerModal.tsx` | tabbed inspector, tabs derived from the registry |
| `components/DestinationConfigFields.tsx` | generic field renderer, driven by `option.fields` |

`components/AppLayout.tsx` matches `/knowledge-store/:id` and renders `KnowledgeProductPage` with the id as a
prop, following the same `PersistentPage` + `useRouteParams` pattern as `/sources/:id`. The route is deep-linkable.

**The visualizer registry is the extension point.** `VISUALIZERS` maps a destination type to
`{label, engine, icon, color, Component}`. The modal builds its tabs from the product's destinations through
`visualizerFor()`, so adding a destination means one writer and one purger in the backend, one catalogue entry,
and one registry entry. A type with no visualizer renders `No visualizer for <type> yet.` instead of an empty tab.
`GraphVisualizer.tsx` was deleted with the destination.

---

## 10. Database, Migration and Tests

- Tables: `knowledge_products`, `knowledge_product_sources`, `knowledge_product_destinations`,
  `knowledge_product_files`. `pipelines.knowledge_product_id` is the renamed foreign key.
- Alembic head: `010_knowledge_products` (`down_revision = 009_pipeline_knowledge_profile`). It renames the three
  tables and the index names, renames the foreign key columns, adds the three schedule columns, creates
  `knowledge_product_files`, deletes the `graph_neo4j` destination rows and deletes `indexed_files` rows whose
  `pipeline_id IS NULL` (the fanout's old state).
- The dev database is SQLite, created by `Base.metadata.create_all`, which never renames a table.
  `init_db()` therefore calls `_ensure_sqlite_renames(sqlite_path)` **before** `create_all` — otherwise
  `create_all` creates an empty `knowledge_products` and the rename fails, orphaning the old table — and
  `_ensure_sqlite_columns` after it. Every statement is individually guarded, so the whole sequence is idempotent.
- `shared-contracts/shared_contracts/knowledge.py` mirrors the real payload: `KnowledgeProductRead`,
  `KnowledgeProductCreate`, `KnowledgeProductUpdate`, `KnowledgeProductSourceRead`,
  `KnowledgeDestinationConfigRead`, `DestinationConfigInput`,
  `SinkType = Literal["vector_qdrant", "lexical_opensearch", "relational_pgvector", "cache_redisvl"]`.
- `rag-retrieval-chat-manager` proxies `/api/knowledge-products` and uses `PATCH` for updates.
- `IndexedFile` and the pipeline path are unchanged; only the fanout moved to the new ledger.

### Tests and scripts

- `backend/tests/test_knowledge_destination_schemas.py` — the catalogue has exactly four destinations and no
  `graph_neo4j`; every entry declares `namespace_fields`; store names differ per product; namespacing replaces a
  shared default but keeps a typed value.
- `backend/tests/test_knowledge_product_files.py` — `resolved_interval_seconds` for live, seconds, minutes, the
  default and the five-second floor; `_apply_schedule` for live clearing both intervals, seconds and minutes
  clearing each other, the `INTERVAL_REQUIRED` error, and keeping a stored interval.
- `backend/scripts/e2e_knowledge_fanout.py` — end-to-end CRUD against the live stores: two products over one
  bucket, differing store names, `422 DESTINATION_STORE_CONFLICT`, `POST /sync` returns 404, add/replace/delete
  propagate to all four sinks, and each product keeps its own copy.
- `backend/scripts/e2e_knowledge_pause.py` — pause-all stops every write; resume-all catches up; a
  per-destination pause excludes exactly that destination; resuming it catches up.
- `backend/scripts/purge_neo4j_legacy.py` — one-shot removal of the `Chunk`/`Document`/`Entity` nodes the removed
  destination wrote. A migration must not do network I/O, so this is a script.

Run them with:

```bash
cd rag-ingestion-manager/backend
uv run pytest tests -q
uv run python scripts/e2e_knowledge_fanout.py
uv run python scripts/e2e_knowledge_pause.py
```

`pytest` must be present in the backend virtualenv (`uv sync --extra dev`); a system-wide `pytest` cannot import
`apps` or `src`.

### Environment

The four destinations need reachable stores. `backend/.env` points at the host-mapped ports:

```
REDIS_URL=redis://localhost:6379/0
QDRANT_URL=http://localhost:6335
MINIO_ENDPOINT=localhost:9000
OPENSEARCH_URL=http://localhost:9200
```

Postgres comes from `docker-compose.yaml` (`pgvector/pgvector:pg16`, database and user `ingestion`). The
`relational_pgvector` destination default `connection_url` is the application database URL; when that is SQLite,
`pg_connection_urls()` skips it and falls back to `postgresql://ingestion:ingestion@localhost:5432/ingestion`.
