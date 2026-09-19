# 01 — Ingestion Overview Dashboard Page

**Last updated:** 2026-09-20

## 1. Executive Summary & Page Purpose
The **Ingestion Overview Dashboard** (`frontend/src/pages/HomePage.tsx`) is the landing page of the `rag-ingestion-manager` frontend. It is rendered by `AppLayout.tsx` for the path `/` (nav entry `{ to: "/", label: "Overview", end: true }`) and is kept mounted persistently, so it is not re-mounted when the user navigates to another page and back.

The page is read-only: it loads three backend lists on mount, renders them as KPI counters, quick links, a recent folder-workspaces grid, and a static multi-sink engine banner. It performs no mutations and has no refresh timer.

---

## 2. UI Layout & Visual Components

```
+------------------------------------------------------------------------------------------+
| Ingestion Manager  |  Overview  |  Folders  |  Sources  |  Knowledge Store                |
+------------------------------------------------------------------------------------------+
| Ingestion Overview                                                                       |
| Ingest documents, manage connected data sources, and orchestrate 5-sink Knowledge         |
| Store fanout sync.                                                                        |
+------------------------------------------------------------------------------------------+
| [ Connected Data Sources | Workspace Folders | Ingested Files | Knowledge Profiles ]      |
+------------------------------------------------------------------------------------------+
| Quick Launch Workspaces:                                                                  |
| [ Data Sources & Storage ]  [ Folders & Files ]                                           |
| [ External Connectors ]  [ Knowledge Store Fanout ]                                       |
+------------------------------------------------------------------------------------------+
| Recent Folder Workspaces                                             [ View All ]          |
| [ <folder name> : N files : relative time ] x up to 6                                     |
+------------------------------------------------------------------------------------------+
| Universal Multi-Sink Knowledge Engine (2026 Edition)        [ Configure Sinks ]           |
| [ Qdrant ] [ OpenSearch ] [ Neo4j ] [ PostgreSQL ] [ RedisVL ]                            |
+------------------------------------------------------------------------------------------+
```

### Component Hierarchy

- **Header** (`components/PageHeader.tsx`, called with `title` and `description` only): renders `<h1 class="page-title">` and `<p class="page-description">`. There are no status badges on this page — `PageHeader` also accepts optional `breadcrumbs` and `actions`, neither of which `HomePage` passes.
- **Metric highlight panels** — four static cards in one CSS grid. Counters are plain `<div>` numbers; labels:

  | Card label | Value rendered | Source |
  |---|---|---|
  | `Connected Data Sources` | `sourcesCount` = `listSources().length` | `GET /api/sources` |
  | `Workspace Folders` | `directories.length` | `GET /api/directories` |
  | `Ingested Files` | `directories.reduce((acc, d) => acc + (d.fileCount \|\| 0), 0)` | derived from `GET /api/directories` (see note below) |
  | `Knowledge Profiles` | `profilesCount` = `listKnowledgeProfiles().length` | `GET /api/knowledge-profiles` |

  Note: `GET /api/directories` returns only `{name, id, created_at}` per directory (`apps/api/routes/directories.py:37-41`). `DirectorySummary.fileCount`/`file_count` are optional and are never populated by that endpoint, so the `Ingested Files` card currently always renders `0`.

- **Quick action grid** — `QUICK_LINKS` (`as const`, 4 entries; the `Document Upload` card was removed on 2026-09-20 with the Upload page). Titles, targets, descriptions and CTA labels as coded:

  | Title | Route | Description (verbatim) | CTA |
  |---|---|---|---|
  | `Data Sources & Storage` | `/sources` | Create NiFi connector sources or manual upload sources. Each source gets its own MinIO bucket. | Manage Sources |
  | `Folders & Files` | `/browse` | Explore virtual directory workspaces and raw object storage contents. | Open Workspace |
  | `External Connectors` | `/sources` | Sync Google Drive, Amazon S3, and Azure Blob Storage into MinIO buckets. | Manage Sources |
  | `Knowledge Store Fanout` | `/knowledge-store` | Manage 5-sink multi-vector fanout sync to Qdrant, OpenSearch, Neo4j, Postgres, & RedisVL. | Manage Knowledge Store |

  `Data Sources & Storage` and `External Connectors` both link to `/sources` (distinct cards, same destination).

- **Recent Folder Workspaces panel** — header with `IconFolder`, title `Recent Folder Workspaces`, and a `View All` ghost button linking to `/browse`. Body states:
  - loading: `Loading workspace folders…`
  - empty: `No workspace folders created yet.` plus a `Create Data Source` button linking to `/sources`
  - populated: `directories.slice(0, 6)` as cards linking to `/browse/{encodeURIComponent(dir.name)}`; each card footer shows `{fileCount ?? file_count ?? 0} file(s)` and `formatRelativeTime(updatedAt ?? updated_at ?? created_at)` (via `frontend/src/utils/format.ts`). Since `GET /api/directories` supplies neither `fileCount` nor `updatedAt`, each card currently reads `0 files` and falls back to `created_at` for the timestamp.
  - There is **no** "Connected Sources Summary Table" on this page, and the source list fetched for the KPI counter is not rendered as a table.

- **Knowledge sink engine banner** — panel titled `Universal Multi-Sink Knowledge Engine (2026 Edition)` with a `Configure Sinks` link to `/knowledge-store`, one paragraph of copy, and five static tiles (no API calls):
  - `Qdrant:` Dense Vector Embeddings (HNSW)
  - `OpenSearch:` BM25 Lexical & Inverted Index
  - `Neo4j:` GraphRAG Entity-Relation Triples
  - `PostgreSQL:` Relational & pgvector ACLs
  - `RedisVL:` Parent-Child & Semantic Cache

---

## 3. Backend APIs & Data Contracts

Only three endpoints are called by this page, all on mount:

| Method | Endpoint | API client function | Used for |
|---|---|---|---|
| `GET` | `/api/sources` | `listSources()` (`api.ts`) | `Connected Data Sources` KPI |
| `GET` | `/api/directories` | `listDirectories()` (`api.ts`) | `Workspace Folders` + `Ingested Files` KPIs, Recent Folder Workspaces grid |
| `GET` | `/api/knowledge-profiles` | `listKnowledgeProfiles()` (`api.ts`) | `Knowledge Profiles` KPI |

There is no `GET /api/files/stats` endpoint in `apps/api/routes/files.py`; the dashboard does not compute or display a storage-usage figure. Aggregate file/page counters are exposed only per pipeline at `GET /api/pipelines/{pipeline_id}/stats`.

### Sample JSON Response (`GET /api/directories`)
Actual response shape (no file counts, no `updated_at`):

```json
[
  {
    "name": "manual-vj",
    "id": "e23cb20a-8a4b-4bfa-a42e-cf6e01a88b50",
    "created_at": "2026-09-16T08:42:01.120Z"
  }
]
```

### Sample JSON Response (`GET /api/sources`)
Serialized by `_source_to_dict()` in `apps/api/routes/sources.py` (abridged to the fields relevant to the dashboard):

```json
[
  {
    "id": "2da1c0d5-5727-4632-9cb9-009c91d4e0e4",
    "name": "v-res",
    "source_type": "minio",
    "is_manual": false,
    "is_local": false,
    "minio_bucket": "source-v-res-2da1c0d5",
    "status": "connected",
    "enabled": true,
    "last_sync_at": "2026-09-16T08:35:12.834Z",
    "total_files": 10,
    "total_size_bytes": 5242880,
    "connector_count": 1,
    "pipeline_ids": [],
    "created_at": "2026-09-15T10:00:00.000Z",
    "updated_at": "2026-09-16T08:35:12.834Z"
  }
]
```

`source_type` is derived at read time as `local_filesystem`, `minio_manual`, or `minio` — it is not stored as an enum in the `sources` table.

---

## 4. Key Workflows & User Interactions

1. **Initial load** — `useEffect(() => { load(); }, [load])` runs once per application mount. `load()` calls the three API functions inside a single `Promise.all`, each with an individual `.catch(() => [])`, so one failing endpoint degrades to an empty list instead of blanking the page; `loading` is cleared in `finally`.
2. **No polling / no auto-refresh** — there is no `setInterval`, websocket, or refetch on focus. Because `AppLayout` keeps `HomePage` mounted (`PersistentPage`), navigating to another page and back does not re-run the fetch; a browser reload is required to refresh the counters.
3. **Navigation** — the four quick cards and the panel buttons (`View All`, `Create Data Source`, `Configure Sinks`) are plain react-router `Link`s; folder cards deep-link into the browse page.
