# 18 — Data Sources

**Last updated:** 2026-10-02

## 1. Executive Summary & Page Purpose

This document covers the sources family of the retrieval frontend. The family has two routes.

| Route | Component | Purpose |
|---|---|---|
| `/sources` | `pages/SourcesPage.tsx` | List, create, sync and delete data sources |
| `/sources/:id` | `pages/SourceDetailPage.tsx` | One source: connectors, catalogue, bucket files |

A source is one MinIO bucket plus zero or more connectors that feed objects into it. The retrieval app reads and writes this state **through the ingestion API on port 8007**. It does not call the retrieval API on 8001. `AppLayout` mounts `SourcesPage` under the exact path test `isSourcesExact` (`AppLayout.tsx:118`, `AppLayout.tsx:178-180`) and `SourceDetailPage` from the `source-detail` branch of `useRouteParams` (`AppLayout.tsx:82-83`, `AppLayout.tsx:242-246`).

The detail page is keyed by the source id, so a change of id remounts it (`AppLayout.tsx:244`). `SourcesPage` is a persistent page: it stays mounted for the whole session and only its visibility changes.

`SourcesPage` and `SourceDetailPage` are ports of the ingestion manager's own pages, which carry more controls. The ingestion pages remain the authority for connector semantics: `../rag-ingestion-manager-docs/03_data_sources_page.md`.

## 2. Data Path

```
+---------------------------------------------------------------------------------+
|  Retrieval frontend (Vite dev server, port 5174)                                |
|    /sources      SourcesPage.tsx                                                   |
|    /sources/:id  SourceDetailPage.tsx + components/Sources/FileBrowser.tsx         |
|                     + components/Sources/ConnectorConfigForm.tsx                  |
|  client: apiFetch -> API_URL = VITE_API_URL ?? http://127.0.0.1:8007              |
+----------------------------------------+----------------------------------------+
                                         |
                                         v  plain cross-origin fetch
+---------------------------------------------------------------------------------+
|  Ingestion backend (port 8007), prefix /api/sources                              |
|  GET    /api/sources                          list, newest first                  |
|  POST   /api/sources                          create, 201                         |
|  GET    /api/sources/{id}                     one source                          |
|  DELETE /api/sources/{id}                     delete the source and its bucket    |
|  POST   /api/sources/{id}/sync                manual sync of every connector       |
|  GET    /api/sources/connectors               NiFi catalogue, 3 entries            |
|  POST   /api/sources/{id}/connectors          attach a connector                   |
|  PATCH  /api/sources/{id}/connectors/{cid}    change a connector                   |
|  DELETE /api/sources/{id}/connectors/{cid}    remove a connector                   |
|  POST   /api/sources/{id}/connectors/{cid}/sync   sync one connector               |
|  GET    /api/sources/{id}/files?prefix=        object keys of the bucket           |
+---------------------------------------------------------------------------------+
```

Every route lives in `apps/api/routes/sources.py` and is mounted by `apps/api/main.py:69`.

## 3. `/sources` — Source List

### 3.1 What the page shows

| Area | Content |
|---|---|
| Header | Title `Data Sources`, a `2026 Engine` pill, one line of description, the `New Source` button |
| Banners | An info banner for a result message, an error banner. Both close with a cross |
| Stat cards | `Total Data Sources`, `Attached Connectors`, `Syncing Sources`, `Isolated MinIO Buckets`. The first three also set the status filter |
| Toolbar | A search input over name and bucket, filter pills `All`, `Active`, `Syncing` and `Error`, a grid and table toggle |
| Content | A card grid or a table, built from the filtered list |
| Create dialog | A modal with one field, `Source Name` |

A card shows the name, a status dot with the raw status, a `StatusBadge`, the connector count, the bucket name with a copy button, then up to four connector badges and `+n more` (`SourcesPage.tsx:83-246`). The card actions are `Sync Now`, a trash button and `Manage`. The whole card is a button for the keyboard: Enter or Space opens the detail page (`SourcesPage.tsx:83-246`).

The table shows `Source Name` with the first 8 characters of the id, `MinIO Storage Bucket`, `Status`, `Connectors`, `Last Updated` and actions (`SourcesPage.tsx:248-351`). The `Connectors` cell prints the total count and the word `connected`, even when the count is zero.

The `Error` pill appears only when at least one source is in error (`SourcesPage.tsx:658-668`). The filter treats `enabled === false` as not active, and `syncing` or `processing` as syncing (`SourcesPage.tsx:530-546`).

### 3.2 State, load and polling

| Item | Value |
|---|---|
| Load | `listSources()` (`SourcesPage.tsx:449-458`) |
| Polling | Every 30000 ms, which is 30 seconds (`SourcesPage.tsx:464`) |
| Visibility gate | The pathname must equal `/sources` (`SourcesPage.tsx:447`, `SourcesPage.tsx:462-466`) |
| Local state | `sources`, `loading`, `error`, `info`, `syncingId`, `deletingId`, `showCreateForm`, `newSourceName`, `creating`, `searchQuery`, `statusFilter`, `viewMode` |

Leaving the page clears the interval, so the polling stops. A non-`ApiError` failure becomes a synthetic `500 UNKNOWN` error through `toApiError` (`SourcesPage.tsx:28-33`).

### 3.3 Create flow

1. `New Source` opens the modal and focuses the name field.
2. The dialog previews the bucket name as `source-{name}-...` while the user types (`SourcesPage.tsx:825-833`).
3. `Create Source` sends `createSource({ name: newSourceName.trim() })` (`SourcesPage.tsx:514`), which is `POST /api/sources` with one JSON field (`api.ts:1664-1670`).
4. On success the page stores an info message, reloads the list and navigates to `/sources/{new.id}` (`SourcesPage.tsx:515-519`).
5. On failure it shows the error and stays on the list.

Server behaviour for this body:

* `name` is required, 1 to 128 characters (`sources.py:66-67`).
* `name` is trimmed. A duplicate name answers `409 SOURCE_EXISTS` (`sources.py:283-286`).
* `source_type` defaults to `minio`, so the request does **not** take the manual-upload branch (`sources.py:281`).
* The bucket name is `{minio_bucket_prefix}-{safe_name}-{first 8 chars of the id}`, where the prefix defaults to `source` (`sources.py:247-251`, `settings.py:65`). The `safe_name` lowercases the name and turns a space or an underscore into a hyphen.
* The server calls `ensure_bucket` and registers the source poller (`sources.py:376-384`).

The created source has `connector_type` null and zero connectors. Nothing feeds the bucket until a connector is attached on the detail page.

### 3.4 Sync flow

`Sync Now`, and the sync icon in the table, call `triggerSourceSync(sourceId)` (`SourcesPage.tsx:479`), which is `POST /api/sources/{id}/sync` (`api.ts:1777-1779`).

* The server sets the source status to `syncing`, clears `error_message`, and enqueues a Pathway sync job (`source_sync.py:36-45`).
* A disabled source answers `{"status": "error", "message": "Source is disabled"}` (`source_sync.py:32-33`).
* The success answer carries `status`, `source_id`, `connector_type` and `minio_bucket`. It carries **no `message` field** (`source_sync.py:50-55`). The page therefore always shows its fallback text, `Sync triggered successfully.` (`SourcesPage.tsx:480`).
* The button is disabled while its own request is in flight, then the list reloads (`SourcesPage.tsx:475-486`).

### 3.5 Delete flow

`Delete` asks `window.confirm` first (`SourcesPage.tsx:493`). On a confirm it calls `deleteSource(sourceId)` (`SourcesPage.tsx:496`), which is `DELETE /api/sources/{id}` (`api.ts:1684-1686`).

The server then:

1. Deletes every `KnowledgeProductSource` and `PipelineSource` link of the source (`sources.py:474-475`).
2. Deletes the local folder for a local source, or the whole MinIO bucket for a bucket source (`sources.py:476-492`).
3. Deletes the source row, commits, stops the poller, and answers `{"status": "deleted", "id": ...}` (`sources.py:493-497`).

This is destructive and it is not undoable. The confirmation names the source. A failure to delete the bucket is logged and does not stop the row delete.

## 4. `/sources/:id` — Source Detail

### 4.1 What the page shows

| Area | Content |
|---|---|
| Header | Breadcrumb line `Overview > Sources > {name}`, the name with a status badge, a bucket pill that copies the name on click, `Back to Sources`, `Sync All Connectors` |
| Stat cards | `Source Status` with the raw status and a time, `Attached Connectors` with a count |
| Tabs | `Connectors Catalogue` with the connector count, `Bucket Storage Files` with the file count |
| Tab 1 | `Active Attached Connectors`, then the `Integration Catalogue` |
| Tab 2 | `FileBrowser` for the bucket |
| Modal | The attach or configure form for one connector |

An attached connector card shows the catalogue icon, the connector type with underscores replaced by spaces, the monitor mode (`LIVE` webhooks or `{n}m interval`), a status badge, the last sync time, then `Sync Now`, `Configure` and a trash button (`SourceDetailPage.tsx:495`).

### 4.2 State, load and polling

| Item | Value |
|---|---|
| Initial load | `getSource(id)`, `listConnectors()`, then `listSourceFiles(id)` (`SourceDetailPage.tsx:126-149`) |
| Polling | Every 20000 ms, which is 20 seconds. Each tick reloads the source and its files (`SourceDetailPage.tsx:151-154`) |
| Cleanup | The interval is cleared and a `mounted` flag blocks late writes (`SourceDetailPage.tsx:156-159`) |
| Local state | `source`, `files`, `loading`, `error`, `info`, `activeTab`, `syncingAll`, `copiedBucket`, `categoryFilter`, the modal flag, `editingConnector`, `connectorForm`, `savingConnector` |

A failed `listSourceFiles` is swallowed and becomes an empty list (`SourceDetailPage.tsx:141-142`). A failed `listConnectors` also does not stop the page (`SourceDetailPage.tsx:135`). The page shows a full-page error only when the source itself did not load (`SourceDetailPage.tsx:273-281`).

### 4.3 The connector catalogue and the attach flow

The catalogue is a hardcoded array of 12 entries in the page itself, `EXTENDED_CATALOG` (`SourceDetailPage.tsx:53-66`). A category filter narrows it to `cloud`, `database`, `files` or `workspace` (`SourceDetailPage.tsx:289-291`). Clicking a card opens the modal with the default config of that connector (`SourceDetailPage.tsx:183-192`).

The modal holds the type-specific fields from `ConnectorConfigForm`, a monitor mode radio pair, and a sync interval field that appears only for `scheduled` (`SourceDetailPage.tsx:755-800`). `defaultConfigFor` gives each type its fields, for example `s3` gets `bucket`, `access_key_id`, `secret_access_key`, `region` and `prefix` (`ConnectorConfigForm.tsx:9-45`).

`Attach Connector` calls `addSourceConnector(source.id, {...})` (`SourceDetailPage.tsx:223`), which is `POST /api/sources/{id}/connectors` (`api.ts:1688-1697`). `Save Changes` in edit mode calls `updateSourceConnector(...)` (`SourceDetailPage.tsx:216`), which is `PATCH /api/sources/{id}/connectors/{cid}` (`api.ts:1699-1709`).

**The catalogue and the server disagree.** The server accepts only three connector types: `google_drive`, `s3` and `azure_blob` (`sources.py:39-43`). Any other type answers `422 INVALID_CONNECTOR` with the valid list (`sources.py:516-520`). The catalogue offers 12 types, so a card for `postgres`, `mysql`, `mongodb`, `web_scraper`, `confluence`, `sftp`, `google_sheets`, `onedrive` or `sharepoint` always fails on save. Only the first three cards can succeed.

Removing a connector asks `window.confirm`, then calls `deleteSourceConnector` (`SourceDetailPage.tsx:242-244`), which is `DELETE /api/sources/{id}/connectors/{cid}` (`api.ts:1711-1713`). A local filesystem source rejects every connector with `422 CONNECTORS_NOT_SUPPORTED` (`sources.py:511-514`).

`Sync Now` on one connector calls `triggerConnectorSync(source.id, connId)` (`SourceDetailPage.tsx:255`). The client function ignores the connector id and posts to `/api/sources/{id}/sync`, the all-connectors route (`api.ts:1765-1767`). A single-connector sync is not available from this page.

`Sync All Connectors` uses the same `POST /api/sources/{id}/sync` route as the list page (`SourceDetailPage.tsx:173`).

### 4.4 The files tab

The tab renders `components/Sources/FileBrowser.tsx` with `allowUpload={false}` and `allowDelete={false}` (`SourceDetailPage.tsx:682-690`). The upload dropzone and the Delete button are therefore not rendered (`FileBrowser.tsx:351`, `FileBrowser.tsx:564`). The tab is read-only. Uploads happen on `/upload` only, which document 19 describes.

The browser itself:

| Behaviour | Detail |
|---|---|
| Data | `listSourceFiles(sourceId)` on mount and on every folder change (`FileBrowser.tsx:98-113`, `FileBrowser.tsx:115-117`) |
| Views | `All Files (Flat)` over the whole key list, or `Folder View` over the current prefix (`FileBrowser.tsx:287-300`) |
| Folders | Derived from the `/` in a key, relative to the current prefix (`FileBrowser.tsx:191-219`) |
| Navigation | Breadcrumb buttons per prefix segment, plus an `up` button that strips the last segment (`FileBrowser.tsx:49-58`, `FileBrowser.tsx:304-330`) |
| Sorting | `Name`, `Size` or `Modified`, from a sort button in the header (`FileBrowser.tsx:500-523`) |
| Paging | `PAGE_SIZE = 20`, `Prev` and `Next` (`FileBrowser.tsx:41`, `FileBrowser.tsx:585-608`) |
| Keyboard | Enter or Space on a row calls the delete handler, arrow keys move the focus between rows (`FileBrowser.tsx:252-269`) |
| Empty state | `Files in this MinIO bucket are automatically ingested and updated via configured connector sync streams.` (`FileBrowser.tsx:483-487`) |

## 5. API Calls — Port 8007

| Method | Path | Client function | Used by |
|---|---|---|---|
| `GET` | `/api/sources` | `listSources()` (`api.ts:1660-1662`) | list, poll |
| `POST` | `/api/sources` | `createSource(body)` (`api.ts:1664-1670`) | create dialog |
| `DELETE` | `/api/sources/{id}` | `deleteSource(id)` (`api.ts:1684-1686`) | list |
| `POST` | `/api/sources/{id}/sync` | `triggerSourceSync(id)` (`api.ts:1777-1779`) | list, detail |
| `GET` | `/api/sources/{id}` | `getSource(id)` (`api.ts:1672-1674`) | detail, poll |
| `GET` | `/api/sources/connectors` | `listConnectors()` (`api.ts:1655-1658`) | detail, result discarded |
| `POST` | `/api/sources/{id}/connectors` | `addSourceConnector(...)` (`api.ts:1688-1697`) | detail |
| `PATCH` | `/api/sources/{id}/connectors/{cid}` | `updateSourceConnector(...)` (`api.ts:1699-1709`) | detail |
| `DELETE` | `/api/sources/{id}/connectors/{cid}` | `deleteSourceConnector(...)` (`api.ts:1711-1713`) | detail |
| `POST` | `/api/sources/{id}/connectors/{cid}/sync` | none. The client posts to the source route instead | not used |
| `GET` | `/api/sources/{id}/files?prefix=` | `listSourceFiles(id, prefix)` (`api.ts:1731-1736`) | detail, browser |

Neither page calls `GET /api/sources/{id}/connectors/{cid}`, `POST /api/sources/{id}/pipeline/{pid}`, `DELETE /api/sources/{id}/pipeline/{pid}`, `PATCH /api/sources/{id}` or `POST /api/sources/{id}/events`.

## 6. Validation and Behaviour Limits

| Rule | Value | Source |
|---|---|---|
| Source name | 1 to 128 characters, trimmed, unique | `sources.py:66-67`, `sources.py:283-286` |
| Duplicate name | `409 SOURCE_EXISTS` | `sources.py:285` |
| Connector type | 1 to 64 characters | `sources.py:50` |
| Connector type allow list | `google_drive`, `s3`, `azure_blob` | `sources.py:39-43` |
| Unknown connector type | `422 INVALID_CONNECTOR` | `sources.py:516-520` |
| Connector on a local source | `422 CONNECTORS_NOT_SUPPORTED` | `sources.py:511-514` |
| Monitor mode | `live` or `scheduled`, default `live` | `sources.py:52` |
| Sync interval | 1 minute or more (`sync_interval_minutes`). The second field allows 5 to 86400 seconds | `sources.py:53-54` |
| Bucket name | `{prefix}-{safe name}-{8 id characters}`, prefix default `source` | `sources.py:247-251`, `settings.py:65` |
| Object list | No paging. The whole bucket is returned. A MinIO failure after 5 seconds returns an empty list and logs a warning | `sources.py:722-775` |
| Source list order | `created_at` descending | `sources.py:269-274` |
| Delete | Removes the links, then the bucket or the local folder, then the row | `sources.py:466-496` |

## 7. Dead or Unreachable Code and Defects

| Finding | Detail | Source |
|---|---|---|
| The API connector catalogue is fetched and thrown away | `const [, setCatalog] = useState<ConnectorOption[]>([])` holds the result of `listConnectors()` and never reads it. The page renders the hardcoded `EXTENDED_CATALOG` instead | `SourceDetailPage.tsx:79`, `SourceDetailPage.tsx:135`, `SourceDetailPage.tsx:139`, `SourceDetailPage.tsx:289-291` |
| Nine catalogue cards cannot succeed | The catalogue offers 12 types. The server accepts 3 | `SourceDetailPage.tsx:53-66`, `sources.py:39-43` |
| `summarizeConnectors` has no caller | Exported helper for a connector status summary. Nothing imports it | `SourcesPage.tsx:51-79` |
| `getConnectorSchema` has no caller | Returns an empty object | `ConnectorConfigForm.tsx:46-48` |
| `updateSource` has no caller | `PATCH /api/sources/{id}` is exported and unused, so name and monitor defaults cannot be changed from this frontend | `api.ts:1676-1682` |
| `linkSourceToPipeline` and `unlinkSourceFromPipeline` have no caller | A source cannot be linked to a pipeline from this frontend | `api.ts:1715-1729` |
| `Open & Visualize` opens the wrong endpoint | The anchor is hardcoded to `http://127.0.0.1:8007/api/sources/{id}/files?key=...`. The list route reads `prefix`, not `key`, so the new tab shows the whole JSON file list. The host is hardcoded, so a non-default port breaks the link | `FileBrowser.tsx:555-562`, `sources.py:722-726` |
| The `allowDelete` flag does not stop the keyboard | With `allowDelete` false the Delete button is hidden, but Enter or Space on a focused row still calls the delete handler. That handler asks `window.confirm` and then really deletes the object | `FileBrowser.tsx:252-256`, `FileBrowser.tsx:171-189`, `SourceDetailPage.tsx:686-687` |
| File tab messages go to the console | `onInfo` logs to the console, so a delete or upload message inside the browser is invisible | `SourceDetailPage.tsx:689` |
| A single-connector sync is really a whole-source sync | `triggerConnectorSync` ignores its second argument | `api.ts:1765-1767` |
| The success message of a sync is always the fallback | The sync route returns no `message` field | `SourcesPage.tsx:480`, `source_sync.py:50-55` |
| `deleteFile`, `renameFile` and the directory calls | Exported by `api.ts` for the browse family only. The sources family does not use them | document 17 |

## 8. What These Pages Do Not Do

* No edit of a source name or of its monitor defaults.
* No pipeline link or unlink from a source.
* No upload and no delete inside the bucket from this frontend.
* No filter or page for the object list beyond the browser's client-side sort and paging.
* No confirmation before `Sync All Connectors`. The delete of a source and the delete of a connector both confirm.
* No retry of a failed load. Only the 20 second poll retries.
