# 11 — Knowledge Store (view only)

**Last updated:** 2026-09-20

## 1. Executive Summary & Page Purpose

The retrieval manager exposes the ingestion manager's Knowledge Products as a **read-only
mirror**. It exists so a RAG pipeline can point at a existing Knowledge Product without
leaving this app, and so the state of that product can be inspected here.

The page never creates, edits or deletes a Knowledge Product. The ingestion manager is the
only writer; every field on screen comes from it. The retrieval manager stores no knowledge
state of its own.

Two routes:

| Route | Component | Purpose |
|---|---|---|
| `/knowledge-store` | `pages/KnowledgeStorePage.tsx` | List every product; `Refresh`; `View` one |
| `/knowledge-store/:id` | `pages/KnowledgeProductPage.tsx` | Read-only configuration view for one product |

Both are view-only ports of the ingestion manager's own Knowledge Store pages, so the two
apps render the same UI. The ingestion equivalents are documented in
`../rag-ingestion-manager-docs/04_knowledge_store_page.md`, which remains the authority for
destination configuration semantics, defaults, store namespacing and the fanout engine.

### 1.1 The read-only contract

| Capability | Present here | Where it lives |
|---|---|---|
| List products | yes | — |
| View one product's configuration | yes | — |
| Live fanout timeline | yes | — |
| Ingested-file ledger | yes | — |
| Inspect destination store contents | yes | — |
| Paused / Running indication | yes | badges only |
| `Refresh` (manual sync) | yes | — |
| Auto re-read on revisit | yes | — |
| `Test Connection` probe | yes | read-only probe |
| Create a product | **no** | ingestion manager |
| Edit a product or a destination | **no** | ingestion manager |
| Pause / resume a product or destination | **no** | ingestion manager |
| Delete a product or a pipeline | **no** | ingestion manager |

`Test Connection` is a connectivity probe, not a mutation, so it stays. The pause and
configure controls that the ingestion detail page carries were deliberately dropped: this
page reports state, it does not set it.

## 2. Routing & Data Path

Both pages call the ingestion backend **directly**. `frontend/src/api.ts` builds every
knowledge call on `apiFetch`, whose base is `API_URL = VITE_API_URL ?? "http://localhost:8007"`.

```
+---------------------------------------------------------------------------------+
|  Retrieval frontend (Vite dev port 5174)                                        |
|  /knowledge-store          KnowledgeStorePage.tsx                               |
|  /knowledge-store/:id      KnowledgeProductPage.tsx                             |
|  client: apiFetch -> API_URL = VITE_API_URL ?? http://localhost:8007             |
|  no dev proxy in frontend/vite.config.ts                                        |
+------------------------------------------------+--------------------------------+
                                                 |
                                                 v  (plain cross-origin fetch)
+---------------------------------------------------------------------------------+
|  Ingestion backend (port 8007)                                                  |
|  GET    /api/knowledge-products                                                 |
|  GET    /api/knowledge-products/{id}                                            |
|  PATCH  /api/knowledge-products/{id}          <- used as the manual-sync trigger |
|  GET    /api/knowledge-products/{id}/files                                      |
|  GET    /api/knowledge-products/{id}/events   <- SSE                            |
|  GET    /api/knowledge-products/{id}/inspect/{destination_type}                  |
|  GET    /api/knowledge-products/destinations/options                             |
|  POST   /api/knowledge-products/{id}/test-connection                             |
+---------------------------------------------------------------------------------+

Mounts but is NOT used by either page:

+---------------------------------------------------------------------------------+
|  Retrieval backend (port 8001) — routes/knowledge.py, prefix /api/knowledge-products |
|  httpx -> (settings.ingestion_service_url or http://localhost:8007)              |
|  6 proxy routes; see section 6                                                   |
+---------------------------------------------------------------------------------+
```

The ingestion API allows `access-control-allow-origin: *`, so the cross-origin calls from
port 5174 succeed. The practical consequence is that this page needs **port 8007 reachable
from the user's browser**. Routing it through the retrieval proxy would reduce that to 8001.

## 3. Refresh: manual sync and automatic sync

The ingestion API has **no sync route by design**. Manual sync was removed when the
product-level poller took over the schedule, so `POST /{id}/sync` returns 404. This page still
offers a manual sync, without changing any ingestion code, by exploiting a documented
property of `PATCH`:

1. `PATCH /api/knowledge-products/{id}` ends with `register_knowledge_poller(product.id)`.
2. `register_knowledge_poller` re-reads the product and **always fires one immediate sync**
   (`src/ingestion_service/core/knowledge_sync.py`: "It always fires one immediate sync so a
   new product does not wait").

`KnowledgeProductUpdateRequest` has every field optional, so an empty body is valid and
changes nothing. `refreshKnowledgeProduct(productId)` in `api.ts` therefore sends `PATCH {}`
with a comment explaining why, and the page re-reads immediately afterwards.

| Trigger | Behaviour |
|---|---|
| `Refresh` on the list | `PATCH {}` for **every** product via `Promise.allSettled`, then `GET /api/knowledge-products` |
| `Refresh` on the detail page | `PATCH {}` for that product, then `GET /{id}` and `GET /{id}/files` |
| Revisiting `/knowledge-store` | `GET /api/knowledge-products` only — a display refresh, no sync |
| Detail page, every 5 s | `GET /{id}` and `GET /{id}/files`, so the timeline keeps moving even when the SSE stream reconnects |
| Opening the detail page | one immediate load, then the 5 s interval |

Auto re-read on revisit is not a mount effect. `AppLayout` keeps every page mounted and toggles
visibility, so a `useEffect(..., [])` runs once per session. The page watches
`location.pathname` instead and re-reads whenever the path becomes `/knowledge-store`.

## 4. UI Layout

### 4.1 List — `/knowledge-store`

```
+---------------------------------------------------------------------------------+
|  Knowledge Store                                                                |
|  "View only — the Knowledge Products configured in the Ingestion Manager."       |
|                                                              [ Refresh ]         |
+---------------------------------------------------------------------------------+
| Total Products | Connected MinIO Buckets | Active RAG Sinks | Fanout Engine      |
| products.length| distinct minio_bucket   | enabled dests    | "4 Parallel Sinks" |
+---------------------------------------------------------------------------------+
| Product card                                                                    |
|  name  [ RUNNING | PAUSED ]  [ status.toUpperCase() ]              [ View -> ]  |
|  description                                                                    |
|  Linked MinIO Source Buckets (n): chips of source name + (minio_bucket)          |
|  Configured Destination Stores: one card per /destinations/options entry         |
|    name, [ RUNNING | PAUSED ], description, per-product store name,              |
|    [ Test Connection ] -> "Connected" / "Failed"                                 |
|  Linked RAG Pipelines (n): cards with qdrant_collection, rag_strategy            |
|    (chunk_size / chunk_overlap), embedding_model; link to /pipelines             |
+---------------------------------------------------------------------------------+
```

`RUNNING` / `PAUSED` is derived, not a stored field: a product is running when
`product.enabled` is true **and** at least one destination is enabled. The second badge is the
ingestion `status` (`IDLE`, `SYNCING`, `SYNCED`, `ERROR`), which reports the last run rather
than the configuration.

Each destination card's own `RUNNING` / `PAUSED` badge reads that destination's `enabled` flag,
which is the same flag the ingestion page's Pause control writes.

### 4.2 Detail — `/knowledge-store/:id`

```
+---------------------------------------------------------------------------------+
| Overview > Knowledge Store > {name}                          [ <- Back ] [ Refresh ]|
| name  [ RUNNING | PAUSED ] [ status ] [ "Scheduled every 10s" ]                  |
+---------------------------------------------------------------------------------+
| Source Buckets | Files Indexed | Pages Indexed | Last Sync                       |
+---------------------------------------------------------------------------------+
| Live Fanout                                                                     |
|   MinIO bucket -> Parse & chunk -> cache_redisvl / lexical_opensearch /          |
|                                    relational_pgvector / vector_qdrant          |
|   Added n | Updated n | Deleted n | Unchanged n | Pages n                        |
|   live event log                                                                 |
+---------------------------------------------------------------------------------+
| Destination Stores (n running)                                                  |
|   one card per destination: name, [ RUNNING | PAUSED ], description,             |
|   per-product store name, last sync, last error, [ Inspect Store ]               |
+---------------------------------------------------------------------------------+
| Ingested Files                                                                  |
|   File Key | Source | Status | Pages | Destinations | Updated                    |
+---------------------------------------------------------------------------------+
|                                                                        [ Reload ]|
+---------------------------------------------------------------------------------+
```

`Inspect Store` opens the destination visualizer, which reads that destination live and, for
Qdrant, renders a clickable UMAP/PCA scatter of the stored vectors.

### 4.3 Components ported from the ingestion manager

These files were copied byte-identical so the two apps render the same UI. They are the reason
this page needed no new visualization code.

| File | Role |
|---|---|
| `hooks/useProductEvents.ts` | SSE subscription returning `{events, connected}` |
| `components/knowledge/LiveFanoutTimeline.tsx` | The pipeline diagram, the counters and the event log |
| `components/visualizers/DestinationVisualizerModal.tsx` | The tabbed store inspector |
| `components/visualizers/index.ts` | `VISUALIZERS` registry + `visualizerFor(type)` |
| `components/visualizers/{Vector,Lexical,Relational,Cache}Visualizer.tsx` | One panel per destination type |

`useProductEvents` uses `fetch` and a `ReadableStream` rather than `EventSource`, because
`EventSource` cannot send the `X-API-Key` header. It keeps the last 300 events and reconnects
after 3 s.

The backend publishes nine event kinds, which is what the timeline renders:
`tick_start`, `tick_done`, `file_start`, `file_synced`, `file_failed`, `file_deleted`,
`destination_start`, `destination_done`, `destination_failed`.

Supporting changes in the retrieval project:

* `index.css` gained the `.fanout-*` rule block and the missing `.status-paused` rule.
* `api.ts` gained `productEventsPath`, `listProductFiles`, `ProductFileEntry`,
  `ProductFilesResponse`, `DestinationInspectData`, `inspectDestinationStore` and
  `refreshKnowledgeProduct`.
* `api.ts` exports `authHeaders` now, because the SSE hook needs it.
* `KnowledgeProduct` gained `monitor_mode`, `sync_interval_seconds`, `sync_interval_minutes`,
  `files_total`, `files_synced`, `files_pending`, `files_failed` and `pages_indexed`. The
  ingestion API always returned these; the retrieval type had omitted them, so the ported page
  could not compile against it.
* `createKnowledgeProduct`, `updateKnowledgeProduct`, `deleteKnowledgeProduct` and
  `KnowledgeProductCreateRequest` were **removed**. The view-only rewrite orphaned them, and
  keeping write bindings for a read-only page contradicts the design.
* `AppLayout.tsx` gained the `knowledge-product` route-param type and the mount block for
  `/knowledge-store/:id`, mirroring the existing `source-detail` pattern.

## 5. Endpoints the pages call

| Method | Path | Client function | Used by |
|---|---|---|---|
| `GET` | `/api/knowledge-products` | `listKnowledgeProducts()` | List |
| `GET` | `/api/knowledge-products/destinations/options` | `getDestinationOptions()` | Both |
| `PATCH` | `/api/knowledge-products/{id}` | `refreshKnowledgeProduct(id)` | Both — empty body; manual sync |
| `POST` | `/api/knowledge-products/{id}/test-connection` | `testDestinationConnection(id, type, config)` | List |
| `GET` | `/api/knowledge-products/{id}` | `getKnowledgeProduct(id)` | Detail |
| `GET` | `/api/knowledge-products/{id}/files` | `listProductFiles(id, {limit: 50})` | Detail |
| `GET` | `/api/knowledge-products/{id}/events` | `useProductEvents(id)` | Detail — SSE |
| `GET` | `/api/knowledge-products/{id}/inspect/{destination_type}` | `inspectDestinationStore(id, type)` | Detail |

Neither page calls `POST`, `DELETE`, `PATCH /{id}/destinations/{destination_id}`,
`POST /{id}/pause-all` or `POST /{id}/resume-all`. Those belong to the ingestion manager.

## 6. Retrieval-backend proxy (present, unused)

`backend/apps/rag-api/src/rag_api/routes/knowledge.py` mounts a same-prefix proxy on port 8001
with 6 routes:

| Method | Path | Behaviour |
|---|---|---|
| `GET` | `/api/knowledge-products` | Forward; 200 required |
| `POST` | `/api/knowledge-products` | Forward; accepts 200/201; returns 201 |
| `GET` | `/api/knowledge-products/{product_id}` | Forward; 200 required |
| `PATCH` | `/api/knowledge-products/{product_id}` | Forward `exclude_unset` body; 200 required |
| `DELETE` | `/api/knowledge-products/{product_id}` | Forward; accepts 200/204; always returns 204 |
| `POST` | `/api/knowledge-products/{product_id}/test-connection` | Forward; 200 required |

**No frontend code calls it.** Both pages use `apiFetch`, which targets 8007. The proxy is
functional — it answers 200 — but it is a parallel path that nothing takes.

Its request/response models come from `shared_contracts.knowledge` (`KnowledgeProductRead`,
`KnowledgeProductCreate`, `KnowledgeProductUpdate`, plus `KnowledgeProductSourceRead`,
`KnowledgeDestinationConfigRead`, `DestinationConfigInput`). The target base is
`getattr(settings, "ingestion_service_url", None) or "http://localhost:8007"`, and `Settings`
declares no `ingestion_service_url`, so the hard-coded fallback always applies. Every call
uses a 15 s timeout, and any `httpx.RequestError` becomes
`503 {"detail": "Ingestion service unavailable: ..."}`.

Two options, if the duplicate path is unwanted: delete the proxy router, or repoint the page at
it. Neither is done here.

## 7. What this page does not do

* No create, edit, pause, resume, configure or delete.
* No pagination, filtering or search over the product list.
* No in-app delete dialog, because nothing here deletes. The ingestion page's `ConfirmDialog`
  stays behind with the controls it guarded.
* `product.sources[].file_count` and per-destination `status` / `error_message` / `last_sync_at`
  are returned by the API. The list card renders the destination error only on the detail page.
* `Settings` has no `guardrails_url` or `ingestion_service_url` field, so both effective values
  are code defaults.

## 8. Verification (2026-09-20)

`tsc --noEmit` reports no errors and `vite build` succeeds. Both pages were loaded in a browser
with the HTTP cache and cookies cleared, collecting console errors, page errors, failed
requests and 4xx/5xx responses.

| Check | Result |
|---|---|
| `/knowledge-store` | clean; no Create, Edit or Delete button in the DOM |
| `/knowledge-store/:id` via `View` | clean; navigates and renders live data |
| Live Fanout | ticks arriving every few seconds |
| Ingested Files | 3 rows with file key, source, `SYNCED`, page count, all four destinations |
| All four `Inspect Store` panels | live contents (Qdrant points, OpenSearch terms, Postgres rows, Redis keys and TTLs) |
| `Refresh` on the list | issues `PATCH` then `GET /api/knowledge-products` |
| `Refresh` on the detail page | issues `OPTIONS` -> `PATCH` -> `GET /{id}` -> `GET /{id}/files` |
| Revisit after leaving to `/prompts` | issues `GET /api/knowledge-products` |
| All 12 retrieval routes swept | 12 of 12 clean |
| Production build (`vite preview`) | detail page clean, live ticks rendering |

The only console entry in dev is `GET /{id}/events net::ERR_ABORTED`, which is React
`StrictMode` unmounting the SSE effect once. The production build shows it does not occur
outside dev.
