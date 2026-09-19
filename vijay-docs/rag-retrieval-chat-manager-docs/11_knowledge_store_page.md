# 11 — Knowledge Store Proxy & Sink Verification Page

**Last updated:** 2026-09-17

## 1. Executive Summary & Page Purpose
The **Knowledge Store page** (`KnowledgeStorePage.tsx`, route `/knowledge-store`) is the retrieval manager's management UI for the ingestion manager's Knowledge Profiles. It lists profiles, shows linked MinIO source buckets, displays and edits the five fanout destinations, triggers a fanout sync, and tests destination connectivity. All knowledge-profile state lives in the ingestion backend (port 8007); the retrieval manager stores none.

Two routing facts matter for this page:

* The page's API client uses `apiFetch`, whose base URL is `VITE_API_URL` (default `http://localhost:8007`). Every profile/source/destination call therefore goes **directly to the ingestion backend**, not to the retrieval backend.
* The retrieval backend additionally mounts a same-prefix proxy router at `/api/knowledge-profiles` (`routes/knowledge.py`) that forwards to `getattr(settings, "ingestion_service_url", None) or "http://localhost:8007"`. `Settings` has no `ingestion_service_url` field (`rag_shared/config.py`), so the hard-coded fallback is always the target. That router's request/response models come from `shared_contracts.knowledge` (`sink_type`, `destination_name`, `connection_uri`, `sync_status`), which matches neither the ingestion API nor the frontend payloads (`destination_type`, `enabled`, `config`, `status`); treat it as a contract-stale proxy, not the page's data path.

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
|  - GET    /api/knowledge-profiles                                                             |
|  - POST   /api/knowledge-profiles                                                             |
|  - GET    /api/knowledge-profiles/{id}                                                        |
|  - PUT    /api/knowledge-profiles/{id}                                                        |
|  - DELETE /api/knowledge-profiles/{id}                                                        |
|  - POST   /api/knowledge-profiles/{id}/test-connection                                        |
|  - POST   /api/knowledge-profiles/{id}/sync                                                   |
|  - GET    /api/knowledge-profiles/destinations/options                                        |
+-----------------------------------------------------------------------------------------------+

Parallel, and NOT used by this page:

+-----------------------------------------------------------------------------------------------+
|  RAG Retrieval backend (port 8001) — routes/knowledge.py, router prefix /api/knowledge-profiles|
|  httpx -> (settings.ingestion_service_url or http://localhost:8007)                            |
|  7 proxy routes (see section 4); no /destinations/options, no /config/litellm-models,          |
|  no /{id}/inspect/{destination_type}                                                          |
+-----------------------------------------------------------------------------------------------+
```

Ports: retrieval frontend `5174` (`frontend/vite.config.ts`), retrieval backend `8001` (`rag_shared/config.py`, `backend/.env.example`), ingestion backend `8007` (`VITE_API_URL` default in `frontend/src/api.ts`).

---

## 3. UI Layout & Visual Components

```
+-----------------------------------------------------------------------------------------------+
|  Knowledge Store Manager                                                                      |
|  "Universal Multi-Sink Fanout Engine — Route MinIO documents to 5 enterprise RAG destinations."|
|  [ Refresh ]                                            [ + New Knowledge Profile ]          |
+-----------------------------------------------------------------------------------------------+
|  Total Profiles  |  Connected MinIO Buckets  |  Active RAG Sinks  |  Fanout Engine Architecture |
|  profiles.length |  distinct minio_bucket    |  enabled destinations | "5 Parallel Sinks" (static)|
+-----------------------------------------------------------------------------------------------+
|  Profile card                                                                                 |
|  - name + status badge (status.toUpperCase(), colour by synced / syncing / other)              |
|  - description                                                                                |
|  - [ Sync All Sinks ] [ edit ] [ delete ]                                                     |
|  - Linked MinIO Source Buckets (n): chips of source name + (minio_bucket)                     |
|  - Configured Destination Stores: one card per /destinations/options entry                    |
|      name, ACTIVE/OFF badge, description, one-line config summary for the known type,          |
|      [ Test Connection ] -> "Connected" / "Failed"                                            |
|  - Linked RAG Pipelines (n): cards with qdrant_collection / rag_strategy (chunk_size /          |
|      chunk_overlap) / embedding_model; per-pipeline [ Delete ]; link to /pipelines             |
+-----------------------------------------------------------------------------------------------+
|  Modal: Configure New / Edit Knowledge Profile                                                |
|  - Profile Name (client-side required: "Profile name is required."), Description              |
|  - Link MinIO Source Buckets: checkbox per source (all selected by default on create)          |
|  - Configure 5 Universal 2026 RAG Destination Stores: per destination an "Enable Fanout"       |
|    checkbox plus one free-text input per key of that destination's default_config              |
|  - Cancel / Create Profile | Update Profile                                                   |
+-----------------------------------------------------------------------------------------------+
```

Behavioural details and limits of the page:

* Four metric cards are computed client-side only: `profiles.length`, the count of distinct `minio_bucket` values across linked sources, the count of enabled destinations, and a static "5 Parallel Sinks" label.
* Destination cards render from `GET /destinations/options`; the config summary line shows a fixed key per destination type (`vector_qdrant` → `collection_name`, `lexical_opensearch` → `index_name`, `graph_neo4j` → `bolt_uri`, `relational_pgvector` → `table_name`, `cache_redisvl` → `index_prefix`).
* Destination config fields are edited as plain text inputs; values are coerced heuristically (`"true"`/`"false"` → boolean, numeric strings → number, everything else stays a string). Objects are stringified for display.
* Only whole-profile sync is offered — there is no per-destination sync, and no `inspect/{destination_type}` visualizer action anywhere in the retrieval frontend.
* "Test Connection" is disabled unless the destination is enabled for that profile; results are shown as "Connected"/"Failed" only (the API message is stored but not rendered).
* Profiles are not paginated or filtered; the full `GET /api/knowledge-profiles` list is rendered.
* Deleting a profile, deleting a linked pipeline, and a failed sync all use browser `confirm`/`alert` dialogs.
* `profile.sources[].file_count` and per-destination `status`/`error_message`/`last_sync_at` are returned by the ingestion API but not rendered.
* The page mounts persistently inside `AppLayout` (`components/AppLayout.tsx`, nav item "Knowledge Store"); `App.tsx` only holds legacy redirects.

---

## 4. Backend APIs & Contracts

### 4.1 Endpoints the page actually calls (ingestion backend, via `apiFetch`)

| Method | Path | Client function | Purpose |
|---|---|---|---|
| `GET` | `/api/knowledge-profiles` | `listKnowledgeProfiles()` | List all profiles with `sources`, `destinations`, `pipelines` |
| `GET` | `/api/knowledge-profiles/{id}` | `getKnowledgeProfile(id)` | Fetch one profile (defined; not called by the page) |
| `POST` | `/api/knowledge-profiles` | `createKnowledgeProfile(body)` | Create profile; body `{name, description, enabled, source_ids, destinations[{destination_type, enabled, config}]}` |
| `PUT` | `/api/knowledge-profiles/{id}` | `updateKnowledgeProfile(id, body)` | Update profile with the same body shape |
| `DELETE` | `/api/knowledge-profiles/{id}` | `deleteKnowledgeProfile(id)` | Delete profile; client expects a `204` |
| `POST` | `/api/knowledge-profiles/{id}/test-connection` | `testDestinationConnection(id, type, config)` | Body `{destination_type, config}`; renders `status` |
| `POST` | `/api/knowledge-profiles/{id}/sync` | `syncKnowledgeProfile(id)` | Trigger fanout sync |
| `GET` | `/api/knowledge-profiles/destinations/options` | `getDestinationOptions()` | `{id, name, category, description, default_config}[]` for destination cards and the modal |
| `GET` | `/api/sources` | `listSources()` | Source checkboxes; fields used: `id`, `name`, `minio_bucket` |
| `DELETE` | `/api/pipelines/{id}` | `deletePipeline(id)` | Delete a linked RAG pipeline from the profile card |

### 4.2 Retrieval-backend proxy surface (`rag-retrieval-chat-manager/backend/apps/rag-api/src/rag_api/routes/knowledge.py`)

| Method | Path | Behaviour |
|---|---|---|
| `GET` | `/api/knowledge-profiles` | Forward to `{ingestion}/api/knowledge-profiles`; 200 required |
| `POST` | `/api/knowledge-profiles` | Forward; accepts 200/201; returns 201 |
| `GET` | `/api/knowledge-profiles/{profile_id}` | Forward; requires 200 |
| `PUT` | `/api/knowledge-profiles/{profile_id}` | Forward `exclude_unset` body; requires 200 |
| `DELETE` | `/api/knowledge-profiles/{profile_id}` | Forward; accepts 200/204; always returns 204 |
| `POST` | `/api/knowledge-profiles/{profile_id}/test-connection` | Forward; requires 200 |
| `POST` | `/api/knowledge-profiles/{profile_id}/sync` | Forward with a 30 s timeout; accepts 200/202 |

Proxy behaviour notes:

* Target base is `getattr(settings, "ingestion_service_url", None) or "http://localhost:8007"` with a trailing slash stripped; `Settings` defines no `ingestion_service_url`, so the fallback always applies.
* Any `httpx.RequestError` becomes `503 {"detail": "Ingestion service unavailable: ..."}`; non-expected upstream status codes are re-raised with the upstream body as `detail`.
* All other calls use a 15 s timeout.
* Request/response models (`KnowledgeProfileCreate`, `KnowledgeProfileUpdate`, `TestConnectionRequest`, `TestConnectionResponse`, `KnowledgeProfileRead`) are imported from `shared_contracts.knowledge`. Their required fields are `sink_type` (`Literal["qdrant","opensearch","neo4j","pgvector","redisvl"]`) and `destination_name`, and the read model exposes `sync_status`; the ingestion API and this page both key on `destination_type`/`enabled`/`config` and read `status`. A page-shaped body (no `sink_type`) is invalid against these models, so the proxy cannot serve this page as written.
