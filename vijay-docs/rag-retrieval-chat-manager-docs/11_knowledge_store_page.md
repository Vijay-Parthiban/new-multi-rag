# 11 — Knowledge Store Proxy & Sink Verification Page

**Last updated:** 2026-09-20

## 1. Executive Summary & Page Purpose
The **Knowledge Store page** (`KnowledgeStorePage.tsx`, route `/knowledge-store`) is the retrieval manager's management UI for the ingestion manager's Knowledge Products. It lists products, shows linked MinIO source buckets, displays and edits the four fanout destinations, and tests destination connectivity. It has no sync trigger: manual sync was removed. All knowledge-product state lives in the ingestion backend (port 8007); the retrieval manager stores none.

The ingestion UI also has a per-product detail page at `/knowledge-store/:id` (`KnowledgeProductPage.tsx`) with the live fanout timeline, the pause controls and the store inspector. The retrieval frontend does not have that page, so this document describes the list page only and names the detail page for context.

Two routing facts matter for this page:

* The page's API client uses `apiFetch`, whose base URL is `VITE_API_URL` (default `http://localhost:8007`). Every product/source/destination call therefore goes **directly to the ingestion backend**, not to the retrieval backend.
* The retrieval backend additionally mounts a same-prefix proxy router at `/api/knowledge-products` (`routes/knowledge.py`) that forwards to `getattr(settings, "ingestion_service_url", None) or "http://localhost:8007"`. `Settings` has no `ingestion_service_url` field (`rag_shared/config.py`), so the hard-coded fallback is always the target. That router's request/response models come from `shared_contracts.knowledge` (`KnowledgeProductRead`, `KnowledgeProductCreate`, `KnowledgeProductUpdate`, plus `KnowledgeProductSourceRead`, `KnowledgeDestinationConfigRead` and `DestinationConfigInput`). The models now match the real payload (`destination_type`, `enabled`, `config`, `status`), so the old contract mismatch is resolved. The proxy is still not the page's data path, because the page calls the ingestion backend directly.

Destination configuration semantics (defaults, typed fields, merge rules, sync fanout) belong to the ingestion manager and are documented in `../rag-ingestion-manager-docs/04_knowledge_store_page.md`.

---

## 2. Cross-Service Routing & Proxy Architecture

```
+-----------------------------------------------------------------------------------------------+
|  RAG Retrieval & Chat Manager frontend (Vite dev port 5174)                                   |
|  - Route: /knowledge-store   (KnowledgeStorePage.tsx)                                         |
|  - Client: apiFetch -> base API_URL = VITE_API_URL ?? http://localhost:8007                    |
+-----------------------------------------------+-----------------------------------------------+
                                                |
                                                v  (plain fetch, no retrieval-backend hop)
+-----------------------------------------------------------------------------------------------+
|  RAG Ingestion Manager backend (port 8007)                                                    |
|  - GET    /api/knowledge-products                                                             |
|  - POST   /api/knowledge-products                                                             |
|  - GET    /api/knowledge-products/{id}                                                        |
|  - PATCH  /api/knowledge-products/{id}                                                        |
|  - DELETE /api/knowledge-products/{id}                                                        |
|  - POST   /api/knowledge-products/{id}/test-connection                                        |
|  - GET    /api/knowledge-products/{id}/files                                                  |
|  - GET    /api/knowledge-products/{id}/events                                                 |
|  - PATCH  /api/knowledge-products/{id}/destinations/{destination_id}                          |
|  - POST   /api/knowledge-products/{id}/pause-all                                              |
|  - POST   /api/knowledge-products/{id}/resume-all                                             |
|  - GET    /api/knowledge-products/destinations/options                                        |
+-----------------------------------------------------------------------------------------------+

Parallel, and NOT used by this page:

+-----------------------------------------------------------------------------------------------+
|  RAG Retrieval backend (port 8001) — routes/knowledge.py, prefix /api/knowledge-products      |
|  httpx -> (settings.ingestion_service_url or http://localhost:8007)                           |
|  6 proxy routes (see section 4); no /destinations/options, no /config/litellm-models,         |
|  no /{id}/inspect/{destination_type}, no /{id}/files, no /{id}/events, no /{id}/pause-all     |
+-----------------------------------------------------------------------------------------------+
```

Ports: retrieval frontend `5174` (`frontend/vite.config.ts`), retrieval backend `8001` (`rag_shared/config.py`, `backend/.env.example`), ingestion backend `8007` (`VITE_API_URL` default in `frontend/src/api.ts`).

---

## 3. UI Layout & Visual Components

```
+-----------------------------------------------------------------------------------------------+
|  Knowledge Store Manager                                                                      |
|  "Universal Multi-Sink Fanout Engine — Route MinIO documents to 4 enterprise RAG destinations."|
|  [ Refresh ]                                   [ Create Knowledge Product ]                  |
+-----------------------------------------------------------------------------------------------+
|  Total Products  |  Connected MinIO Buckets  |  Active RAG Sinks  |  Fanout Engine Architecture|
|  products.length |  distinct minio_bucket    |  enabled destinations | "4 Parallel Sinks" (static)|
+-----------------------------------------------------------------------------------------------+
|  Product card                                                                                 |
|  - name + status badge (status.toUpperCase(), colour by synced / syncing / other)              |
|  - description                                                                                |
|  - [ edit ] [ delete ]                                                                        |
|  - Linked MinIO Source Buckets (n): chips of source name + (minio_bucket)                     |
|  - Configured Destination Stores: one card per /destinations/options entry                    |
|      name, ACTIVE/OFF badge, description, one-line config summary for the known type,          |
|      [ Test Connection ] -> "Connected" / "Failed"                                            |
|  - Linked RAG Pipelines (n): cards with qdrant_collection / rag_strategy (chunk_size /          |
|      chunk_overlap) / embedding_model; per-pipeline [ Delete ]; link to /pipelines             |
+-----------------------------------------------------------------------------------------------+
|  Modal: Configure New / Edit Knowledge Product                                                |
|  - Profile Name (client-side required: "Profile name is required."), Description              |
|  - Link MinIO Source Buckets: checkbox per source (all selected by default on create)          |
|  - Configure 4 Universal RAG Destination Stores: per destination an "Enable Fanout"           |
|    checkbox plus one free-text input per key of that destination's default_config              |
|  - Cancel / Create Profile | Update Profile                                                   |
+-----------------------------------------------------------------------------------------------+
```

Behavioural details and limits of the page:

* Four metric cards are computed client-side only: `products.length`, the count of distinct `minio_bucket` values across linked sources, the count of enabled destinations, and a static "4 Parallel Sinks" label.
* Destination cards render from `GET /destinations/options`. Each option declares `namespace_fields`, and the config summary line reads the option's own namespace field instead of a hardcoded destination id: `collection_name` for `vector_qdrant`, `index_name` for `lexical_opensearch`, `index_prefix` for `cache_redisvl`, and `schema_name.table_name` for `relational_pgvector`.
* Destination config fields are edited as plain text inputs; values are coerced heuristically (`"true"`/`"false"` → boolean, numeric strings → number, everything else stays a string). Objects are stringified for display.
* There is no sync trigger. `syncKnowledgeProfile` is removed and manual sync is gone, so the page offers no whole-product sync and no per-destination sync. The `inspect/{destination_type}` visualizer action and the per-destination Pause / Resume controls live on the ingestion per-product detail page, not in the retrieval frontend.
* "Test Connection" is disabled unless the destination is enabled for that product; results are shown as "Connected"/"Failed" only (the API message is stored but not rendered).
* Products are not paginated or filtered; the full `GET /api/knowledge-products` list is rendered.
* Deleting a product and deleting a linked pipeline use browser `confirm`, and a failed delete uses `alert`. The page has no in-app dialog component.
* `product.sources[].file_count` and per-destination `status`/`error_message`/`last_sync_at` are returned by the ingestion API but not rendered.
* The page mounts persistently inside `AppLayout` (`components/AppLayout.tsx`, nav item "Knowledge Store"); `App.tsx` only holds legacy redirects.

---

## 4. Backend APIs & Contracts

### 4.1 Endpoints the page actually calls (ingestion backend, via `apiFetch`)

| Method | Path | Client function | Purpose |
|---|---|---|---|
| `GET` | `/api/knowledge-products` | `listKnowledgeProducts()` | List all products with `sources`, `destinations`, `pipelines` |
| `GET` | `/api/knowledge-products/{id}` | `getKnowledgeProduct(id)` | Fetch one product (defined; not called by the page) |
| `POST` | `/api/knowledge-products` | `createKnowledgeProduct(body)` | Create a product; body `{name, description, enabled, source_ids, destinations[{destination_type, enabled, config}]}` |
| `PATCH` | `/api/knowledge-products/{id}` | `updateKnowledgeProduct(id, body)` | Update a product with the same body shape |
| `DELETE` | `/api/knowledge-products/{id}` | `deleteKnowledgeProduct(id)` | Delete a product; client expects a `204` |
| `POST` | `/api/knowledge-products/{id}/test-connection` | `testDestinationConnection(id, type, config)` | Body `{destination_type, config}`; renders `status` |
| `GET` | `/api/knowledge-products/destinations/options` | `getDestinationOptions()` | `{id, name, category, description, default_config, namespace_fields}[]` for destination cards and the modal |
| `GET` | `/api/sources` | `listSources()` | Source checkboxes; fields used: `id`, `name`, `minio_bucket` |
| `DELETE` | `/api/pipelines/{id}` | `deletePipeline(id)` | Delete a linked RAG pipeline from the product card |

The ingestion API also exposes five routes that this page does not call: `GET /{id}/files`,
`GET /{id}/events` (SSE), `PATCH /{id}/destinations/{destination_id}`, `POST /{id}/pause-all` and
`POST /{id}/resume-all`. They belong to the ingestion per-product detail page.

### 4.2 Retrieval-backend proxy surface (`rag-retrieval-chat-manager/backend/apps/rag-api/src/rag_api/routes/knowledge.py`)

| Method | Path | Behaviour |
|---|---|---|
| `GET` | `/api/knowledge-products` | Forward to `{ingestion}/api/knowledge-products`; 200 required |
| `POST` | `/api/knowledge-products` | Forward; accepts 200/201; returns 201 |
| `GET` | `/api/knowledge-products/{product_id}` | Forward; requires 200 |
| `PATCH` | `/api/knowledge-products/{product_id}` | Forward `exclude_unset` body; requires 200 |
| `DELETE` | `/api/knowledge-products/{product_id}` | Forward; accepts 200/204; always returns 204 |
| `POST` | `/api/knowledge-products/{product_id}/test-connection` | Forward; requires 200 |

Proxy behaviour notes:

* Target base is `getattr(settings, "ingestion_service_url", None) or "http://localhost:8007"` with a trailing slash stripped; `Settings` defines no `ingestion_service_url`, so the fallback always applies.
* Any `httpx.RequestError` becomes `503 {"detail": "Ingestion service unavailable: ..."}`; non-expected upstream status codes are re-raised with the upstream body as `detail`.
* All calls use a 15 s timeout.
* Request/response models (`KnowledgeProductCreate`, `KnowledgeProductUpdate`, `KnowledgeProductRead`) are imported from `shared_contracts.knowledge`, which also declares `KnowledgeProductSourceRead`, `KnowledgeDestinationConfigRead` and `DestinationConfigInput`. The read model exposes `status`, `monitor_mode`, the two interval fields, the four file counters and `pages_indexed`. The field names match the ingestion payload, so the old mismatch is resolved and a page-shaped body validates. The `SinkType` literal is now the four destination ids, and the old `sink_type` / `destination_name` / `connection_uri` / `fanout_mode` / `sync_status` / `last_synced_at` fields are gone.
* `test-connection` forwards a plain `dict` body, because the proxy no longer imports a typed `TestConnectionRequest` / `TestConnectionResponse` pair.
