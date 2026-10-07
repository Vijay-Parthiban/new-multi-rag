# 17 — Folders & File Browser

**Last updated:** 2026-10-02

## 1. Executive Summary & Page Purpose

This document covers the browse family of the retrieval frontend. The family has three routes.

| Route | Component | Purpose |
|---|---|---|
| `/browse` | `pages/BrowsePage.tsx` | Select one MinIO source, list its objects, preview one object |
| `/browse/:name` | `pages/DirectoryPage.tsx` | Show the files of one folder workspace |
| `/browse/:name/view/:fileId` | `pages/FileViewerPage.tsx` | Preview one stored file and its folder neighbours |

The family has no sidebar entry. The retrieval sidebar links 10 entries and none of them points here (`components/AppLayout.tsx:24-35`). The pages are reachable by URL, from the `/upload` page, and from the page's own empty-state buttons.

**These pages call the ingestion API on port 8007.** They do not call the retrieval API on 8001. Every call goes through `apiFetch`, whose base is `API_URL = VITE_API_URL ?? "http://127.0.0.1:8007"` (`api.ts:6`). The dev server of the retrieval frontend runs on port 5174 (`vite.config.ts:8`). Section 6 lists every call.

### 1.1 Two different stores are both called "folder"

| Term | Meaning | Page | Store |
|---|---|---|---|
| Source | One MinIO bucket, one bucket per source record | `BrowsePage` | MinIO object storage |
| Folder workspace | A directory under `storage/local_sources/<name>` | `DirectoryPage` | local filesystem |

`/browse` browses source buckets. `/browse/:name` browses a folder workspace. The two pages share no data and no state.

## 2. Routing

The retrieval app does not use `<Route>` for its pages. `App.tsx` holds the legacy redirects and one catch-all that renders `AppLayout` (`App.tsx:20-28`). `AppLayout` parses the pathname with `useRouteParams` (`AppLayout.tsx:60-91`) and mounts a page when a branch matches.

The checks run in this order (`AppLayout.tsx:61-89`):

| Order | Path pattern | Result | Note |
|---|---|---|---|
| 1 | `/browse/:name/view/:fileId` | `{name, fileId, type: "viewer"}` | |
| 2 | `/directories/:name/view/:fileId` | the same viewer shape | legacy |
| 3 | `/files/:id/view` | `{name: undefined, fileId, type: "viewer"}` | legacy |
| 4 | `/browse/:name` | `{name, type: "directory"}` | |
| 5 | `/directories/:name` | the same directory shape | legacy |
| 6 | `/sources/:id` | `{id, type: "source-detail"}` | document 18 |
| 7 | `/knowledge-store/:id` | `{id, type: "knowledge-product"}` | document 11 |

`AppLayout` then renders `DirectoryPage` for `type === "directory"` (`AppLayout.tsx:227-231`) and `FileViewerPage` for `type === "viewer"` (`AppLayout.tsx:233-240`). Both pages receive their parameters as props, so they do not need to read the URL again.

The exact-path test `isBrowseExact` accepts `/browse` and `/directories` and mounts `BrowsePage` (`AppLayout.tsx:117`, `AppLayout.tsx:175-177`).

### 2.1 Legacy `/directories` redirects

`App.tsx` redirects the three old paths:

| Old path | Redirect | Source |
|---|---|---|
| `/directories` | `Navigate` to `/browse` | `App.tsx:23` |
| `/directories/:name` | `/browse/{name}` | `App.tsx:24`, component at `App.tsx:4-7` |
| `/directories/:name/view/:fileId` | `/browse/{name}/view/{fileId}` | `App.tsx:25`, component at `App.tsx:9-12` |

The redirect uses `replace`, so the browser history does not keep the old URL.

There is no redirect for `/files/:id/view`. That path falls through the catch-all, matches branch 3, and renders `FileViewerPage` with no folder name. The page then reads the folder name from the file record and replaces the URL with the current `/browse` form (`FileViewerPage.tsx:42-44`).

### 2.2 Data path

```
+-------------------------------------------------------------------------------+
|  Retrieval frontend (Vite dev server, port 5174)                              |
|    /browse                      BrowsePage.tsx     listSources, listSourceFiles
|    /browse/:name                DirectoryPage.tsx  listDirectoryFiles, renameFile,
|                                                    deleteFile
|    /browse/:name/view/:fileId   FileViewerPage.tsx getFile, listDirectoryFiles
|    /directories*                App.tsx redirects to /browse*
|  client: apiFetch -> API_URL = VITE_API_URL ?? http://127.0.0.1:8007          |
|  no dev proxy in vite.config.ts                                               |
+---------------------------------------+---------------------------------------+
                                        |
                                        v  plain cross-origin fetch
+-------------------------------------------------------------------------------+
|  Ingestion backend (port 8007)                                                |
|  GET    /api/sources                         source list                      |
|  GET    /api/sources/{id}/files              object keys of one bucket        |
|  GET    /api/sources/{id}/files/content      one object's bytes               |
|  GET    /api/directories/{name}/files        file records of one folder       |
|  GET    /api/files/{id}                      one file record                  |
|  GET    /api/files/{id}/view                 one file's bytes, inline         |
|  PATCH  /api/files/{id}                      rename, asynchronous job         |
|  DELETE /api/files/{id}                      delete, asynchronous job         |
+-------------------------------------------------------------------------------+
```

`API_URL` points at port 8007 for both stores. The MinIO calls and the folder calls share one base.

## 3. `/browse` — Source and Object Browser

`BrowsePage` has no route parameter. It reads two lists and shows a modal preview.

### 3.1 What the page shows

| Area | Content |
|---|---|
| Header | Title, description, breadcrumbs `Overview > Folders / Sources`, `Refresh Files` and `Upload Files` actions |
| Source toolbar | A select of every source, with name, bucket and connector count. Beside it: bucket, total file count, connector count |
| Search row | A substring filter over `file.key`, plus `Showing n of m file(s)` |
| File table | `File Key / Name`, `Size`, `Last Modified`, `Actions` |
| Preview modal | Tabs `Rendered Visualizer`, `Raw Code / Text`, `Metadata & Links` |

The `Upload Files` action is a link to `/upload` without state.

### 3.2 State and load order

| State | Set by |
|---|---|
| `sources`, `loadingSources` | `loadSources` (`BrowsePage.tsx:32-44`) |
| `selectedSourceId` | defaults to the first source (`BrowsePage.tsx:36-38`) |
| `files`, `bucketName`, `loadingFiles` | `loadFiles` (`BrowsePage.tsx:50-61`) |
| `searchTerm`, `selectedFile`, `fileContent`, `loadingContent`, `viewMode` | user actions |

Two effects drive the page (`BrowsePage.tsx:63-71`): one loads the source list on mount, the second loads the objects of the selected source. The second effect runs again when the selection changes.

**There is no polling and no pathname watcher.** `AppLayout` keeps the page mounted for the whole session, so the source list loads once per session. A source that is created on another page does not appear here until the browser reloads. `Refresh Files` reloads only the object list of the selected source. It does not reload the source list.

### 3.3 API calls

`listSources()` (`BrowsePage.tsx:35`), `listSourceFiles(selectedSourceId)` (`BrowsePage.tsx:52`), `getSourceFileContent(...)` on open (`BrowsePage.tsx:80`).

`getSourceFileContent` uses a bare `fetch(url)` and sends no `X-API-Key` header (`api.ts:1757-1764`). When `VITE_API_KEY` is set, the header-less call fails and the modal shows `[Error loading file content: ...]`. The same applies to `getSourceFileContentUrl`, which is also used as the `src` of the image and PDF frames (`BrowsePage.tsx:421`, `BrowsePage.tsx:449`).

### 3.4 The preview modal

`handleOpenFile` sets `viewMode` back to `preview`, clears the old content and fetches the new content (`BrowsePage.tsx:72-87`). On an error it stores the error text into `fileContent`, so the Raw tab shows the message.

The Preview tab picks a renderer from the file extension:

| Extension | Renderer |
|---|---|
| `png`, `jpg`, `jpeg`, `gif`, `webp`, `svg` | `<img>` against the content endpoint (`BrowsePage.tsx:421`) |
| `csv` | A comma-split table (`BrowsePage.tsx:96-118`, used at `BrowsePage.tsx:429-430`) |
| `json` | `JSON.parse` then a pretty-printed block, or the raw text on a parse error (`BrowsePage.tsx:433-442`) |
| `pdf` | An `<iframe>` against the content endpoint (`BrowsePage.tsx:449-455`) |
| anything else | `MarkdownMessage` over the text |

The Metadata tab shows key, bucket, size in bytes, `last_modified` and a link to the raw endpoint (`BrowsePage.tsx:394`). The footer holds a download link with the `download` attribute (`BrowsePage.tsx:466-470`) and a close button.

## 4. `/browse/:name` — Folder Workspace

`DirectoryPage` renders the files of one folder workspace.

| Area | Content |
|---|---|
| Header | The folder name as title, breadcrumbs `Overview > Folders > {name}` |
| Actions | `Refresh`, `Open viewer` when a synced file exists, `Upload here` with `state.directory` |
| Panel | `n files`, then a table of `Name`, `Status`, `Size`, `Updated`, actions |

Row behaviour:

| File status | Name cell | Row actions |
|---|---|---|
| `synced` | Link to the viewer | `View` |
| `duplicate` | Plain text, plus `Same as {duplicate_of_file_name}` | `Original` when `duplicate_of_file_id` exists |
| any other | Plain text, plus `error_message` when set | Rename and Delete |

### 4.1 State and polling

`listDirectoryFiles(name)` on load (`DirectoryPage.tsx:28`). A `setInterval` repeats the call every 300000 ms, which is 5 minutes (`DirectoryPage.tsx:42`). The effect runs only while the page is visible: `isVisible` is true when the pathname equals `/browse/{name}` or `/directories/{name}` (`DirectoryPage.tsx:37`, `DirectoryPage.tsx:39-44`). Leaving the page clears the interval.

### 4.2 Rename flow

1. `Rename` stores the file id and puts the current name into the input. The button is disabled for `processing` and `duplicate` files (`DirectoryPage.tsx:197`).
2. `Save` calls `renameFile(fileId, newName.trim())`, which sends `PATCH /api/files/{id}` with `{"new_name": ...}` (`api.ts:169-175`).
3. The server answers `202` with `{"job_id": ..., "status": "processing"}` and does the rename in the background (`files.py:85-90`).
4. The page reloads the list at once. The new name appears only after the worker finishes the job.
5. An empty or whitespace-only name returns early and closes nothing (`DirectoryPage.tsx:47-48`).

`new_name` has 1 to 512 characters (`files.py:21-22`).

### 4.3 Delete flow

`Delete` calls `deleteFile(fileId)` at once (`DirectoryPage.tsx:60`). It sends `DELETE /api/files/{id}` (`api.ts:177-179`). The server answers `202` with a job id (`files.py:93-96`) and does the delete in the background. The button is disabled only for `processing` files (`DirectoryPage.tsx:209`).

**There is no confirmation dialog on this page.** A single click starts the delete.

### 4.4 What the page reuses

`Upload here` and the empty-state `Upload files` button pass `state.directory` to `/upload` (`DirectoryPage.tsx:89`, `DirectoryPage.tsx:118`). Document 19 describes the upload page. `Open viewer` opens the first synced file, or nothing when no file is synced (`DirectoryPage.tsx:67`, `DirectoryPage.tsx:84-88`).

## 5. `/browse/:name/view/:fileId` — File Preview

`FileViewerPage` shows one file and the other files of the same folder.

| Area | Content |
|---|---|
| Top bar | Breadcrumbs `Overview > Folders > {folder} > {file}`, a count line `n synced · n syncing · n duplicate`, `Refresh` |
| Sidebar | Every file of the folder with its status badge and size. A synced file is a link, any other status is static |
| Main panel | The file name, one status message, then the preview frame |

### 5.1 Load order

1. `getFile(activeFileId)` reads the record (`FileViewerPage.tsx:37`, `api.ts:161-163`).
2. The folder name comes from the route, or from `meta.directory_name` when the route has none (`FileViewerPage.tsx:38`).
3. When the route had no folder name, the page replaces the URL with `/browse/{dir}/view/{fileId}` (`FileViewerPage.tsx:42-44`). This is the `/files/:id/view` legacy path.
4. `listDirectoryFiles(dir)` fills the sidebar (`FileViewerPage.tsx:46`).

A `setInterval` repeats the whole load every 300000 ms, which is 5 minutes (`FileViewerPage.tsx:60`). The effect runs only while the pathname contains `/view/{fileId}` (`FileViewerPage.tsx:55-62`).

### 5.2 Preview rules

The frame is `<iframe src="{API_URL}/api/files/{id}/view">` (`FileViewerPage.tsx:28-31`, rendered at `FileViewerPage.tsx:166-168`). It renders only when the file status in the sidebar list is `synced` (`FileViewerPage.tsx:68`). The endpoint itself also refuses a file that is not synced or has no stored path, and answers `404 FILE_NOT_AVAILABLE` (`files.py:68-82`).

| Status | Message |
|---|---|
| `processing` | `This file is still syncing. Preview will appear when status is synced.` |
| `failed` | `Sync failed: {error_message}`, or `Unknown error` |
| `duplicate` | `Duplicate upload — not stored on disk.` plus the original file link |
| none of the above and not synced | `Select a synced file from the sidebar to preview it.` |

The `Refresh` button repeats the load. Navigation inside the sidebar keeps the folder and swaps the file id.

### 5.3 The legacy `/files/:id/view` branch

`activeFileId` accepts three sources in this order: the `routeFileId` prop, the `fileId` param, then the `id` param (`FileViewerPage.tsx:18`). `AppLayout` always passes the prop, so the two param fallbacks serve the legacy `/files/:id/view` path only. `initialDir` has the same shape (`FileViewerPage.tsx:19`).

## 6. API Calls — Port 8007

All calls are cross-origin from the frontend port 5174 to the ingestion port 8007. The ingestion API allows every origin (`apps/api/main.py:52-53`, `allow_origins=["*"]`), so the calls succeed.

| Method | Path | Client function | Used by |
|---|---|---|---|
| `GET` | `/api/sources` | `listSources()` (`api.ts:1660-1662`) | `/browse` |
| `GET` | `/api/sources/{id}/files` | `listSourceFiles(id, prefix)` (`api.ts:1731-1736`) | `/browse` |
| `GET` | `/api/sources/{id}/files/content?key=` | `getSourceFileContent(id, key)` (`api.ts:1757-1764`) | `/browse` |
| `GET` | `/api/directories/{name}/files` | `listDirectoryFiles(name)` (`api.ts:165-167`) | `/browse/:name`, viewer |
| `GET` | `/api/files/{id}` | `getFile(id)` (`api.ts:161-163`) | viewer |
| `GET` | `/api/files/{id}/view` | Built inline from `API_URL` (`FileViewerPage.tsx:29`) | viewer frame |
| `PATCH` | `/api/files/{id}` | `renameFile(id, name)` (`api.ts:169-175`) | `/browse/:name` |
| `DELETE` | `/api/files/{id}` | `deleteFile(id)` (`api.ts:177-179`) | `/browse/:name` |

Server side, all eight routes live in `apps/api/routes/` of the ingestion project: `sources.py:722`, `sources.py:925` and `sources.py:266` for the source calls, `directories.py:44` for the folder list, and `files.py:58`, `files.py:68`, `files.py:85`, `files.py:93` for the file calls. `apps/api/main.py:65-71` mounts every router.

The browse pages do **not** call `GET /api/directories` (the folder list) and do not call the chunked upload routes. `listDirectories` and the `DirectorySummary` type are exported by `api.ts` with no caller anywhere in the retrieval frontend (`api.ts:151-159`).

## 7. Validation and Behaviour Limits

| Rule | Value | Source |
|---|---|---|
| Rename length | 1 to 512 characters | `files.py:21-22` |
| Rename and delete response | `202` with `{"job_id", "status": "processing"}` | `files.py:85-96` |
| Deleted files in a folder list | Filtered out of the list query | `directories.py:51` |
| File view precondition | Status `synced` and a stored path, else `404 FILE_NOT_AVAILABLE` | `files.py:71-72` |
| Object list per source | No pagination. The whole bucket is returned. A MinIO failure after 5 seconds returns an empty list and logs a warning | `sources.py:722-775` |
| Folder file order | `created_at` descending | `directories.py:53` |
| Source list order | `created_at` descending | `sources.py:269-274` |
| Upload size limit | None on the source-file path. The server reads each upload into memory | `sources.py:806-883` |

## 8. Dead or Unreachable Code

| Finding | Detail | Source |
|---|---|---|
| Stray text node in the modal | A second copy of the bucket and size line renders as loose text between the modal header and the tab bar. It is a JSX child of the modal panel, not an element | `BrowsePage.tsx:338` |
| Non-`ApiError` failures are hidden | Every catch block stores `null` when the error is not an `ApiError`, so the alert bar stays empty | `BrowsePage.tsx:39-41`, `DirectoryPage.tsx:30-32`, `FileViewerPage.tsx:48-50` |
| `download` attribute on a cross-origin link | The content link points at port 8007. A browser ignores `download` for a cross-origin URL, so the file opens instead of saving `[INFERENCE]` | `BrowsePage.tsx:466-470` |
| Prop fallbacks never run | `AppLayout` always passes `routeName` and `routeNavigate`, so the `useParams` and `useNavigate` fallbacks are dead | `DirectoryPage.tsx:15-17`, `AppLayout.tsx:229` |
| The `/directories/:name` clause of `isVisible` is unreachable | `App.tsx` redirects that path before the page can render | `DirectoryPage.tsx:37`, `App.tsx:24` |
| Param fallbacks in the viewer | `routeFileId` and `routeDir` always win in the current mount, so the param branch serves the legacy `/files/:id/view` path only | `FileViewerPage.tsx:18-19` |
| `listDirectories` and `DirectorySummary` | Exported, no caller in this frontend | `api.ts:151-159` |

## 9. What These Pages Do Not Do

* No delete from `/browse`. The object list is read-only.
* No upload from `/browse`. The action links to `/upload`.
* No folder creation. `/browse/:name` shows an existing workspace only.
* No pagination and no server-side search. `/browse` filters the loaded array in the browser.
* No automatic refresh of the source list on `/browse`.
* No confirmation dialog before a file delete on `/browse/:name`.
