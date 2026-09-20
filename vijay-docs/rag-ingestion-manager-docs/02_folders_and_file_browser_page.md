# 02 — Folders & File Browser Page

**Last updated:** 2026-09-20

## 1. Executive Summary & Page Purpose

The sidebar item labeled **Folders** (`/browse`) covers three distinct pages that share the `/browse` URL prefix but operate on different data:

| Route | Component | Data source | Purpose |
|---|---|---|---|
| `/browse` | `BrowsePage.tsx` | MinIO buckets belonging to configured **Sources** | Browse/list files inside a source bucket, open one, visualize or download the raw object |
| `/browse/:name` | `DirectoryPage.tsx` | **Upload folders** (the `directories` table) | List the files of one upload folder; rename/delete files; open the file viewer |
| `/browse/:name/view/:fileId` | `FileViewerPage.tsx` | Upload folders | Preview one synced file inside an iframe served by the backend |

Important: the nav label and the page title disagree. The nav item is "Folders" (`frontend/src/components/AppLayout.tsx:14`) while `BrowsePage` renders the title **"MinIO Sources & Files Browser"** (`frontend/src/pages/BrowsePage.tsx:136`). `/browse` does **not** show upload folders; upload folders are only reachable through `/browse/:name`. In the reverse direction, `/browse/:name` does not browse MinIO buckets.

A fourth, **component-level** browser exists — `components/Sources/FileBrowser.tsx` — which is embedded in the Sources page (`SourceDetailPage`) and in the Sources list drawer. It is not mounted on any `/browse` route. It is the only surface with folder-navigation, upload and pagination controls (sections 3.5 and 6), and since 2026-09-20 it is the **only** upload surface in the frontend.

There is **no** directory-creation page and **no** directory-deletion action anywhere in the UI or API. Folder workspaces are now written only by clients that call the chunked-upload API directly; the frontend no longer has such a caller.

---

## 2. Routing

Routing is split between `App.tsx` (legacy redirects only) and `AppLayout.tsx` (persistent mounting + path parsing). `App.tsx` renders only three redirect routes plus a `*` catch-all that always renders `AppLayout` (`frontend/src/App.tsx:23-27`).

| Path | Rendered by | Mechanism |
|---|---|---|
| `/browse` and `/directories` | `BrowsePage` | `isBrowseExact = path === "/browse" \|\| path === "/directories"` (`AppLayout.tsx:97`, mounted at `:143-145`) |
| `/browse/:name` | `DirectoryPage` | regex `^\/browse\/([^/]+)\/?$` (`AppLayout.tsx:59`), mounted at `:161` |
| `/directories/:name` (legacy) | `DirectoryPage` | regex only (`AppLayout.tsx:63-64`); also receives `/directories/:name/view/:fileId` and `/files/:id/view` via viewer regexes (`:50-56`) |
| `/browse/:name/view/:fileId` | `FileViewerPage` | regex `^\/browse\/([^/]+)\/view\/([^/]+)` (`AppLayout.tsx:47`), mounted at `:166-172` |
| `/sources/:id` | `SourceDetailPage` | regex (`AppLayout.tsx:67-68`) |
| `/directories` | → redirect to `/browse` | `App.tsx:23` |
| `/directories/:name` | → redirect to `/browse/:name` | `App.tsx:24`, `LegacyFolderRedirect` (`:4-7`) |
| `/directories/:name/view/:fileId` | → redirect to `/browse/:name/view/:fileId` | `App.tsx:25`, `LegacyViewerRedirect` (`:9-12`) |

Pages are mounted persistently and toggled with CSS (`PersistentPage`, `AppLayout.tsx:37-47`); dynamic pages are conditionally rendered from the parsed params. `DirectoryPage` and `FileViewerPage` both accept their params as props (`routeName`/`routeFileId`) and fall back to `useParams` when used outside `AppLayout` (`DirectoryPage.tsx:15-16`, `FileViewerPage.tsx:17-19`).

Neither page runs timers unless its path is active:

- `DirectoryPage` polls `load()` every `300000` ms (5 minutes) while the path is exactly `/browse/${name}` or `/directories/${name}` (`DirectoryPage.tsx:37-44`).
- `FileViewerPage` polls the same interval while the path contains `/view/${activeFileId}` (`FileViewerPage.tsx:55-62`).

---

## 3. UI Layout & Visual Components

### 3.1 `/browse` — BrowsePage (MinIO sources)

```
+-----------------------------------------------------------------------+
| MinIO Sources & Files Browser            [Refresh Files][Manage Sources]|
| breadcrumb: Overview / Folders / Sources                               |
+-----------------------------------------------------------------------+
| Selected MinIO Source: [ <source name> (<bucket>) - N connector(s) v ] |
|                        Bucket: <bucket>  Total Files: N  Connectors: N |
+-----------------------------------------------------------------------+
| [ Search files by name or key... ]      Showing X of Y file(s)         |
| +-------------------------------------------------------------------+ |
| | File Key / Name | Size | Last Modified |          Actions         | |
| | <key>           | 1.2 KB | 3m ago      | Open & Visualize          | |
| +-------------------------------------------------------------------+ |
+-----------------------------------------------------------------------+
```

- Header: title and description "Select an existing MinIO source bucket to browse files, open, and visualize content directly." with actions **Refresh Files** (re-calls `listSourceFiles` for the current source) and a **Manage Sources** link to `/sources` (`BrowsePage.tsx:135-154`).
- Source selector: `<select>` of all sources returned by `GET /api/sources`; each option is `name (minio_bucket) — N connector(s)`. The first source is auto-selected (`BrowsePage.tsx:31-36`, `:180-205`). If no sources exist the page renders "No sources configured. Create a source first." instead of the selector (`:181-183`).
- Bucket/stat strip (only when a source is selected): bucket name (falls back to the source's `minio_bucket`), total file count, connector count (`BrowsePage.tsx:207-221`).
- Search: single text input, placeholder "Search files by name or key..." (`:211`). Filtering is a case-insensitive substring match on `file.key` only (`:87-89`). The counter reads `Showing {filtered} of {total} file(s)` (`:221`).
- File table columns: **File Key / Name**, **Size**, **Last Modified**, **Actions** (`:234-269`). Size uses `formatSize` and time uses `formatRelativeTime` (`frontend/src/utils/format.ts:1-19`). There is no sorting control on this page.
- Each row has a linked key (opens the viewer modal) and an **Open & Visualize** button that does the same thing (`BrowsePage.tsx:252-268`).
- Empty/loading states: "Loading files from MinIO bucket..." and "No files found in this MinIO source bucket." (`:226-232`).
- Errors render as an alert with `error.code: error.message` (`:156-160`).

### 3.2 Viewer modal on `/browse`

Clicking a file sets `selectedFile`, resets the view mode to `preview`, and fetches the content as text via `getSourceFileContent` (`BrowsePage.tsx:74-84`). On failure the pane shows `[Error loading file content: ...]` (`:80-82`).

The modal has a fixed overlay (click outside or the close button clears the selection), a header showing the key, bucket and byte-accurate size, three tabs, and a footer (`BrowsePage.tsx:279-474`):

| Tab (label as implemented) | Content |
|---|---|
| Rendered Visualizer (line 343) | Format dispatch, see table below |
| Raw Code / Text (line 350) | `<pre>` with `white-space: pre-wrap; word-break: break-all` containing the fetched text (`:404-408`) |
| Metadata & Links (line 357) | Table of File Key, MinIO Bucket, File Size (formatted + raw bytes), Last Modified (raw ISO string), and a "Direct Stream URL" link to `getSourceFileContentUrl(...)` (`:367-403`) |

Rendered Visualizer dispatch (`BrowsePage.tsx:411-456`), keyed on the lowercased extension:

| Extension | Rendering | URL used |
|---|---|---|
| `png`, `jpg`, `jpeg`, `gif`, `webp`, `svg` | `<img>` | `getSourceFileContentUrl` (direct endpoint, not the fetched text) (`:417-425`) |
| `csv` | HTML table built by `renderCsvTable` — naive `split(",")` per line, first line as header (`:94-131`, `:427-428`) | fetched text |
| `json` | Pretty-printed with `JSON.stringify(parsed, null, 2)`; falls back to a plain `<pre>` when parsing throws (`:431-441`) | fetched text |
| `pdf` | `<iframe>` 60vh tall | `getSourceFileContentUrl` (`:444-451`) |
| anything else | `MarkdownMessage content={content}` (Markdown rendering) (`:455`) | fetched text |

Footer: **Download File** (anchor with `download` attribute pointing at the content URL) and **Close Visualizer** (`BrowsePage.tsx:464-472`).

Note: a stray line of JSX at `BrowsePage.tsx:336` renders a literal `Bucket: … | Size: …` text node between the header and the tab strip.

### 3.3 `/browse/:name` — DirectoryPage (upload folder)

```
+-----------------------------------------------------------------------+
| <folder name>          [Refresh][Open viewer][Manage Sources]          |
| breadcrumb: Overview / Folders / <folder name>                         |
+-----------------------------------------------------------------------+
| N files                                                               |
| Name (status badge, "Same as X" note, error) | Status | Size | Updated |
|  View | Original | Rename | Save | Cancel | Delete                     |
+-----------------------------------------------------------------------+
```

- Header title is the folder name; description "Files with syncing status update automatically in the background."; breadcrumbs Overview → Folders (`/browse`) → folder (`DirectoryPage.tsx:63-73`).
- Actions: **Refresh** (`load()`), **Open viewer** (only when a file with `status === "synced"` exists; links to `/browse/{name}/view/{firstSynced.id}`), **Manage Sources** → `/sources` (`DirectoryPage.tsx:75-90`).
- Panel toolbar shows `N file(s)` (`:100-104`).
- Empty state: file icon, "This folder is empty", and an **Upload files** button that navigates to `/sources` (where manual-upload sources live) (`:107-117`).
- Table columns: **Name**, **Status**, **Size**, **Updated**, and an icon-only actions header (`:126-135`). Status is rendered by `StatusBadge`, which maps `processing` → "Syncing", `synced` → "Synced", `failed` → "Failed", `duplicate` → "Duplicate" (`components/StatusBadge.tsx:1-7`). The backend statuses are `processing`, `synced`, `failed`, `deleted`, `duplicate` (`backend/src/shared/db/models.py:22-27`); `deleted` rows never reach the UI because the listing endpoint filters them out.
- Name cell: a link to the viewer when `status === "synced"`, otherwise plain text; duplicates additionally show "Same as {duplicate_of_file_name}"; a non-duplicate failure shows `error_message` (`:141-161`).
- Row actions (`DirectoryPage.tsx:164-214`):
  - **View** — link to `/browse/{name}/view/{id}`, only for `synced`.
  - **Original** — link to the duplicate's original file, only when `status === "duplicate"` and `duplicate_of_file_id` is set.
  - **Rename** — opens an inline input pre-filled with `original_name`, placeholder `new-name.pdf`, with **Save** and **Cancel**. Disabled when status is `processing` or `duplicate`. Renaming an empty/whitespace value is a no-op (`:46-48`, `:196-205`).
  - **Delete** — disabled while `processing` (`:208-213`). There is no confirmation dialog on this page (unlike `FileBrowser`, section 3.5).

### 3.4 `/browse/:name/view/:fileId` — FileViewerPage

- Top bar: breadcrumb Overview → Folders → folder → filename (`FileViewerPage.tsx:87-94`) and a stats line `{synced} synced · {processing} syncing · {duplicate} duplicate` plus **Refresh** (`:96-103`).
- Left sidebar lists every file in the folder with a status badge and size; only `synced` files are links to `/browse/{dir}/view/{id}`, all others render as static rows (`:113-138`).
- Main panel: title = current filename, then exactly one status-dependent block (`:141-168`):
  - `processing` → info alert "This file is still syncing. Preview will appear when status is synced."
  - `failed` → error alert "Sync failed: {error_message ?? 'Unknown error'}"
  - `duplicate` → warning alert "Duplicate upload — not stored on disk.", "Same content as {name}", plus a **View original** link when `duplicate_of_file_id` exists
  - `synced` → `<iframe className="viewer-frame" src={viewUrl}>` where `viewUrl = `${API_URL}/api/files/{id}/view`` (`:28-31`, `:166-168`)
  - otherwise → "Select a synced file from the sidebar to preview it."
- If the route has no `:name` segment, the page loads the file metadata first and replaces the URL with `/browse/{meta.directory_name}/view/{id}` (`FileViewerPage.tsx:37-43`).
- Auth caveat: the iframe URL is built from `API_URL` with no credentials appended (`FileViewerPage.tsx:28-31`). Only `getSourceFileContentUrl` appends the `api_key` query parameter (`api.ts:1364-1370`). With `API_KEY` configured, the viewer iframe receives 401 responses.

### 3.5 `FileBrowser` component (Sources page only)

`components/Sources/FileBrowser.tsx` is a self-contained MinIO browser with props `sourceId`, `bucketName`, `files`, `onDelete`, `onError`, `onInfo`, `allowUpload` (default `false`), `allowDelete` (default `false`), `allowPreview` (default `false`) (`FileBrowser.tsx:15-34`, `:71-81`). It is not mounted by any `/browse` route; it is the file view on the Sources page and in the Sources list drawer.

- Toolbar shows the bucket name plus the current `prefix`; a two-button toggle switches between **All Files (Flat)** and **Folder View** (`:301-315`).
- Path bar: `root` button (reloads with empty prefix), one crumb per prefix segment (clicking navigates to that segment), and an `↑ up` button using `parentPrefix` (`:50-62`, `:312-355`).
- When `allowUpload` is true it renders a dropzone (click, drag-and-drop, or Enter/Space) that uploads via `uploadSourceFiles` and reloads the current prefix; queued files can be removed individually, plus **Upload N file(s)** and **Clear** (`:360-440`). Default (disabled) state shows the empty-state hint that files are ingested automatically by connector sync streams (`:493-497`).
- Folder section: derived purely client-side from the returned keys — every `key` containing a `/` after the current prefix contributes a folder row with an item count; clicking it loads `prefix + name + "/"` (`:201-219`, `:445-475`).
- File table: sortable headers Name / Size / Modified (`SortKey = "name" | "size" | "modified"`, default `name`; sorting is ascending only and there is no descending toggle) (`:40`, `:98`, `:222-243`, `:505-540`).
- Pagination: `PAGE_SIZE = 20`; page resets to 0 when prefix or sort key changes; footer reads `Page {n} of {total} ({count} files)` (`:42`, `:238-250`, `:600-625`).
- Row keyboard support: Enter/Space triggers delete **only when delete is allowed**, ArrowUp/ArrowDown moves focus between rows (`:267-287`).
- Actions per row, computed as `hasRowActions = canDelete || allowPreview` (`:264-265`):
  - **Open & Visualize** — rendered only when `allowPreview` is true; links to `/api/sources/{sourceId}/files/content?key={key}` (the content endpoint, relative to the API). No caller passes `allowPreview`, so it never shows today.
  - **Delete** — rendered only when `allowDelete` or an `onDelete` prop is set; asks `window.confirm("Delete {key} from the bucket?")` then calls the `onDelete` prop or `deleteSourceFile` (`:181-197`).
  - When neither applies the **Actions column is omitted entirely** and rows are not focusable for deletion.
- Who passes what (2026-09-20): the Sources detail page passes `allowUpload` and `allowDelete` only for `minio_manual` and legacy local sources; the Sources drawer does the same through `canManageFiles`. A connector bucket therefore renders Name / Size / Modified with no Actions column, and a manual bucket renders Delete but not Open & Visualize.
- The `/browse` **BrowsePage** is a separate surface with its own "Open & Visualize" button (section 3.1). It was not changed.

---

## 4. Backend APIs & Data Contracts

All routes live on the ingestion backend (`apps/api/main.py`, port 8007). **Every** route is behind `verify_api_key` (`apps/api/main.py:36`).

### 4.1 Authentication

`verify_api_key` accepts the key from the `X-API-Key` header **or** the `api_key` query parameter, and additionally allows the key to be omitted entirely when the configured key is empty (`shared-libs/platform-common/src/platform_common/auth.py:19-36`). `/health`, `/docs`, `/openapi.json` and `/redoc` bypass auth (`:11`).

The frontend sends `X-API-Key` on all `apiFetch` calls (`api.ts:12-14`, `:51-60`); the raw-content URL helper appends `api_key` so that `<img>`, `<iframe>` and `<a download>` requests are authenticated (`api.ts:1364-1370`). Chunk PUTs use the header (`api.ts:106-109`).

### 4.2 MinIO source browsing

| Method | Endpoint | Handler | Notes |
|---|---|---|---|
| `GET` | `/api/sources` | `sources.py:274` | Source list used by the selector |
| `GET` | `/api/sources/{source_id}/files?prefix=` | `sources.py:752` | Returns `{source_id, bucket, files[]}`; MinIO listing has a 5 s timeout and degrades to an empty list on failure (`sources.py:789-802`); local-filesystem sources are listed from `storage_root()/local_sources/{folder}` (`:764-777`) |
| `POST` | `/api/sources/{source_id}/files` | `sources.py:836` | Multipart field names accepted: `file` and/or `files` (`:847-856`). Empty MinIO upload raises `EMPTY_FILE` (`:900`). Triggers a background sync (`:904`) |
| `DELETE` | `/api/sources/{source_id}/files?key=` | `sources.py:914` | `key` is required |
| `GET` | `/api/sources/{source_id}/files/content?key=` | `sources.py:955` | Returns raw bytes with the media type guessed from the key; missing object → `FILE_NOT_FOUND` (404) (`:988-990`) |

Source file list entry (`sources.py:797-803`, typed as `SourceFileEntry` in `api.ts:1244-1248`):

```json
{
  "key": "invoices/2026-q1.pdf",
  "size": 49356,
  "last_modified": "2026-09-16T08:35:12+00:00"
}
```

The list endpoint returns only `key`, `size` and `last_modified` per file; there is no per-entry `content_type`, `etag`, `chunks_count` or `status`.

### 4.3 Upload folders and files

| Method | Endpoint | Status | Handler |
|---|---|---|---|
| `GET` | `/api/directories` | 200 | `directories.py:37` — returns `[{name, id, created_at}]` ordered by name |
| `GET` | `/api/directories/{name}/files` | 200 | `directories.py:44` — excludes `deleted` files, newest first; unknown folder → `DIRECTORY_NOT_FOUND` (404) via `get_directory` |
| `GET` | `/api/files/{file_id}` | 200 | `files.py:58` — single file + `directory_name`; `deleted` → `FILE_NOT_FOUND` (404) |
| `GET` | `/api/files/{file_id}/view` | 200 | `files.py:68` — `FileResponse` with `Content-Disposition: inline` and the stored media type (fallback `application/octet-stream`) |
| `PATCH` | `/api/files/{file_id}` | 202 | `files.py:85` — body `{"new_name": str}` (1–512 chars); returns `{job_id, status: "processing"}` |
| `DELETE` | `/api/files/{file_id}` | 202 | `files.py:93` — returns `{job_id, status: "processing"}` |
| `POST` | `/api/uploads/init` | 201 | `uploads.py:24` |
| `PUT` | `/api/uploads/{upload_id}/chunks/{chunk_index}` | 204 | `uploads.py:43` |
| `POST` | `/api/uploads/{upload_id}/complete` | 202 | `uploads.py:58` |
| `POST` | `/api/files/{file_id}/append/init` | 201 | `files.py:99` — appending requires `status == "synced"` else 409 `FILE_NOT_SYNCED` |
| `POST` | `/api/files/{file_id}/append/{upload_id}/complete` | 202 | `files.py:127` |

`FileRecord` payload (`directories.py:14-33`, `files.py:32-56`):

```json
{
  "id": "…",
  "original_name": "report.pdf",
  "mime_type": "application/pdf",
  "size_bytes": 49356,
  "content_hash": "…64 hex…",
  "client_content_hash": "…64 hex…",
  "hash_verified": true,
  "status": "synced",
  "error_message": null,
  "duplicate_of_file_id": null,
  "duplicate_of_file_name": null,
  "created_at": "…",
  "updated_at": "…"
}
```

`GET /api/files/{file_id}` adds `directory_name` (`files.py:40`). Statuses are `processing`, `synced`, `failed`, `deleted`, `duplicate` (`models.py:22-27`); the UI surfaces `processing`, `synced`, `failed` and `duplicate` badges, and the file list hides `deleted` rows.

### 4.4 Complete-upload response

`POST /api/uploads/{id}/complete` returns one of (`service.py:28-110`):

```json
{"file_id":"…","job_id":"…","status":"processing","content_hash":"…","client_content_hash":"…","hash_verified":true}
```

or, when the hash already exists in the same folder:

```json
{"file_id":"…","job_id":null,"status":"duplicate","hash_verified":true,
 "duplicate_of_file_id":"…","duplicate_of_file_name":"report.pdf"}
```

---

## 5. Key Workflows & User Operations

1. **Browse a source and preview a file** — select a source, optionally filter, click the key or **Open & Visualize**. The modal fetches text for the raw/preview panes and uses the direct content URL for images/PDF/download (`BrowsePage.tsx:74-84`, `:411-472`).
2. **Open the dedicated viewer** — from a folder row (**View**) or the **Open viewer** header action; the iframe streams the stored file inline (`files.py:78-82`).
3. **Upload into a folder** — no longer possible from the UI. The chunked-upload client (`uploadFileChunked`) was removed on 2026-09-20 with the Upload page; call the chunked-upload API directly (section 6) if a folder workspace is needed.
4. **Rename a file** — inline input in `DirectoryPage`; optimistic UI updates when `load()` re-runs after the 202 response, so the row shows `processing` until the worker finishes (`DirectoryPage.tsx:46-56`, `storage.py:119-142`).
5. **Delete a file** — `DirectoryPage` (no confirmation) or `FileBrowser` (with confirmation). Both are soft deletes: a worker job marks `status = deleted` and unlinks the file from disk (`operations.py:102-114`).
6. **Duplicate upload** — a `duplicate` row appears with a pointer to the original; nothing is written to disk for it (`service.py:64-86`, `duplicates.py:27-52`).

---

## 6. Chunked Upload, Hashing & Dedup

Client side (`api.ts:79-117`, `hash.ts:2-8`) — **removed on 2026-09-20**, recorded here for the API contract:

1. `CHUNK_SIZE = 5 * 1024 * 1024` (5 MiB) — `api.ts:10` (also removed).
2. `totalChunks = max(1, ceil(size / CHUNK_SIZE))`.
3. SHA-256 of the whole file was computed in the browser with `crypto.subtle.digest` and lowercased to 64 hex chars (`hash.ts:2-8`) — this is `client_content_hash`. `computeFileHash` still exists in `hash.ts` but is now unreferenced.
4. `POST /api/uploads/init` with `directory_name`, `file_name`, `total_chunks`, `total_size`, `mime_type`, `client_content_hash`.
5. Each chunk is sliced and sent as `multipart/form-data` field `chunk` to `PUT /api/uploads/{upload_id}/chunks/{i}`. Any non-OK response aborts the loop.
6. `POST /api/uploads/{upload_id}/complete`.

A direct caller must send all three requests itself: there is no client helper any more.

Server side:

| Step | Behaviour | Evidence |
|---|---|---|
| init | Validates `total_chunks >= 1`, `total_size >= 1`, requires `client_content_hash`; normalizes the hash and sanitizes both names; creates the `ChunkUpload` row and `temp/{upload_id}/` | `uploads.py:15-23`, `chunks.py:15-55` |
| chunk PUT | Empty body → 422 `EMPTY_CHUNK`; index outside `[0, total_chunks)` → 422 `INVALID_CHUNK_INDEX`; chunk written as `temp/{upload_id}/chunk_%06d` and the index recorded | `uploads.py:43-55`, `chunks.py:57-80` |
| stitch | All indices must be present (else 409 `INCOMPLETE_UPLOAD` with `missing_chunks`) and each chunk file must exist on disk (else 409 `MISSING_CHUNK_FILE`); the stitched byte count must equal `total_size` (else 422 `SIZE_MISMATCH`) | `chunks.py:82-113` |
| content check | `filetype` magic-byte detection on the stitched file; unknown types become `application/octet-stream`; blocked media type or extension → 422 `FILE_TYPE_BLOCKED` | `validator.py:40-77` |
| hash verify | Server recomputes SHA-256 in 1 MiB reads and compares to `client_content_hash`; mismatch → 422 `CORRUPTION_DETECTED` with both hashes in `details` | `hashing.py:33-46` |
| dedup | Look up a file in the same directory with the same `content_hash` and status `processing` or `synced` | `duplicates.py:9-24` |
| duplicate path | A `duplicate` record is created with `duplicate_of_file_id` and `error_message = "Duplicate of {original}"`; no staging move, no disk write, `job_id` is `null` | `duplicates.py:27-52`, `service.py:64-86` |
| new path | Move the stitched file to `staging/{job_id}/{file_name}`, create the `processing` record + `upload` job, enqueue it | `chunks.py:116-119`, `storage.py:42-85` |
| worker | Moves staging → `uploads/{directory}/{12-hex}-{sanitized_name}`, sets `relative_path`, sizes and hashes, status `synced`; failures set the file to `failed` with the exception text | `operations.py:17-40`, `:129-140` |
| temp cleanup | `temp/{upload_id}` removed and the `ChunkUpload` row deleted after completion | `service.py:108-110` |

Stored-name rule: `unique_stored_name` = `uuid4().hex[:12] + "-" + sanitize_file_name(name)`, and `relative_path` is `uploads/{directory}/{stored_name}` (`paths.py:67-69`, `operations.py:29-34`). Rename keeps the 12-hex prefix already present in `stored_name` (or generates a new one) and rebuilds `{prefix}-{new_name}` (`operations.py:86-98`); renames are **not** re-checked for duplicates, unlike appends (`operations.py:59-66`, `duplicates.py:55-78`).

---

## 7. Validation, Limits & Error Handling

### 7.1 Name/content validators

| Rule | Implementation |
|---|---|
| Directory name: `^[a-z0-9][a-z0-9_-]{0,63}$` after `strip().lower()`; 1–64 chars, lowercase letters/digits/hyphen/underscore, must start alphanumeric. Failure → 422 `INVALID_DIRECTORY_NAME` | `paths.py:8-20` |
| File name: basename only (`Path(name).name`), rejects empty/`.`/`..`, replaces every char outside `[\w.\- ]` with `_`, truncates to 512 chars. Failure → 422 `INVALID_FILE_NAME` | `paths.py:9`, `:23-27` |
| Blocked extension set: `mp4, mov, avi, mkv, webm, wmv, flv, m4v, mp3, wav, ogg, aac, flac, m4a, wma, aiff`; blocked MIME prefixes `video/`, `audio/`. Checked twice — by name and then by magic bytes | `validator.py:8-12`, `:15-37`, `:40-77` |
| Content hash must match `^[a-f0-9]{64}$` after trim/lowercase; otherwise 422 `INVALID_CONTENT_HASH` | `hashing.py:7-19` |
| Rename body `new_name` length 1–512 | `files.py:21-22` |
| Upload body: `directory_name` 1–64, `file_name` 1–512, `total_chunks >= 1`, `total_size >= 1`, `client_content_hash` exactly 64 chars | `uploads.py:15-22` |

### 7.2 Error codes

| HTTP | Code | Trigger |
|---|---|---|
| 404 | `FILE_NOT_FOUND` | Unknown/deleted file record (`files.py:64-65`, `service.py:40`); missing MinIO object when fetching content (`sources.py:988-990`) |
| 404 | `FILE_NOT_AVAILABLE` | `view` on a file that is not `synced` or has no `relative_path` (`files.py:71-72`) |
| 404 | `FILE_MISSING` | `view` where the path no longer exists on disk (`files.py:75-76`) |
| 404 | `DIRECTORY_NOT_FOUND` | Listing files of a folder that does not exist (`storage.py:33-39`) |
| 404 | `UPLOAD_NOT_FOUND` | Unknown chunk-upload session (`chunks.py:62`, `service.py:24`) |
| 404 | `SOURCE_NOT_FOUND` | Unknown source id on the sources endpoints (`sources.py:757-758`, `:843-844`, `:921-922`, `:962-963`) |
| 409 | `INCOMPLETE_UPLOAD` / `MISSING_CHUNK_FILE` | Completing before all chunks land (`chunks.py:85-91`, `:98-103`) |
| 409 | `DUPLICATE_FILE` | Append result collides with another file in the folder (`duplicates.py:70-78`) |
| 409 | `FILE_NOT_RENAMEABLE` | Rename of a `processing` or `duplicate` file (`storage.py:126-127`) |
| 409 | `FILE_DELETED` / `ALREADY_DELETED` | Rename of a deleted file (`storage.py:124-125`); delete of an already deleted file (`storage.py:148-149`); append to a deleted file (`storage.py:95-96`) |
| 409 | `FILE_NOT_SYNCED` | Append target not yet synced (`files.py:108-111`, `storage.py:97-98`) |
| 422 | `INVALID_DIRECTORY_NAME`, `INVALID_FILE_NAME`, `FILE_TYPE_BLOCKED`, `INVALID_CONTENT_HASH`, `INVALID_CHUNK_COUNT`, `INVALID_FILE_SIZE`, `INVALID_CHUNK_INDEX`, `EMPTY_CHUNK`, `SIZE_MISMATCH`, `CORRUPTION_DETECTED`, `FILE_REQUIRED`, `EMPTY_FILE`, `NO_STORED_FILE` | See 7.1 and section 6 |

`ValidationError` maps to 422, `ConflictError` to 409 and `NotFoundError` to 404 (`core/errors.py:1-28`), translated to the JSON envelope `{"error": {"code", "message", "details"}}` consumed by `ApiError` in the frontend (`api.ts:16-50`).

### 7.3 Limits and gaps that are frequently mis-stated

- **No file-size limit is enforced anywhere.** The removed Upload page displayed "Max size 100MB per file." as static text; no server or client code ever checked it. The only size checks are `total_size >= 1` and the stitch size-equality test.
- **No maximum chunk count** and no cap on request body size in the application code.
- **The extension blocklist was client-side only** and lived in the removed `UploadPage` (video/audio). It is gone, so files the old page rejected can now be uploaded to a source bucket; the backend blocklist (`validator.py`) still applies to the chunked-upload path.
- **Folder creation is implicit** and **folder deletion does not exist**: `POST /api/uploads/init` creates the directory row on first use (`storage.py:21-30`), and no endpoint removes it. Deleting the last file leaves an empty folder in `/api/directories`.
- **Source uploads bypass all of the above**: `POST /api/sources/{id}/files` writes straight to MinIO using the sanitized filename with no hashing, dedup, size or extension validation beyond multipart parsing (`sources.py:884-901`).
- **Deletes are asynchronous.** `PATCH`/`DELETE /api/files/{id}` return 202 with a job id; the UI only reflects the outcome after its next `load()` (`files.py:85-96`, `DirectoryPage.tsx:46-62`).
