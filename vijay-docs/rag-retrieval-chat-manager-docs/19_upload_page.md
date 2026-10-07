# 19 — Document Upload

**Last updated:** 2026-10-02

## 1. Executive Summary & Page Purpose

The retrieval frontend mounts one upload page at `/upload`. It writes files into the ingestion platform through the **ingestion API on port 8007**, not through the retrieval API on 8001.

| Item | Value |
|---|---|
| Route | `/upload` |
| Component | `pages/UploadPage.tsx` |
| Mount | `isUpload = path === "/upload"` (`AppLayout.tsx:120`), rendered in a `PersistentPage` (`AppLayout.tsx:186-188`) |
| Sidebar entry | none. The sidebar links 10 entries and this is not one of them (`AppLayout.tsx:24-35`) |

The page has two targets. The source target writes objects into an existing MinIO source bucket. The folder target writes files into a folder workspace through the legacy chunked upload.

**The ingestion app does not mount this page since 2026-09-20.** The ingestion frontend has no `pages/UploadPage.tsx`, and its `AppLayout` has no `/upload` branch. The removal is recorded in `../rag-ingestion-manager-docs/05_document_upload_page.md`. That document also states that the chunked-upload client helper was deleted with the page. The retrieval app kept its own copy of both files, so this page and `uploadFileChunked` live in the retrieval frontend only. `POST/PUT /api/uploads/*` stays mounted in the backend, and this page is now its only UI caller.

## 2. Data Path

```
+----------------------------------------------------------------------------------+
|  Retrieval frontend (Vite dev server, port 5174)                                 |
|    /upload   UploadPage.tsx                                                       |
|  client: apiFetch -> API_URL = VITE_API_URL ?? http://127.0.0.1:8007              |
|  plus one raw fetch for each chunk, with no X-API-Key header                      |
+---------------------------------------+------------------------------------------+
                                        |
                                        v  plain cross-origin fetch
+----------------------------------------------------------------------------------+
|  Ingestion backend (port 8007)                                                   |
|  Source target                                                                   |
|    POST   /api/sources/{source_id}/files        multipart, field name "file"      |
|  Folder target (legacy chunked upload)                                           |
|    POST   /api/uploads/init                     creates the upload session        |
|    PUT    /api/uploads/{upload_id}/chunks/{i}   one 5 MiB chunk per request       |
|    POST   /api/uploads/{upload_id}/complete     stitch, verify, enqueue, 202      |
+----------------------------------------------------------------------------------+
```

The source route lives in `apps/api/routes/sources.py:806`. The three upload routes live in `apps/api/routes/uploads.py:24`, `uploads.py:43` and `uploads.py:58`. All four are mounted by `apps/api/main.py:65-69`.

## 3. What the Page Shows

| Area | Content |
|---|---|
| Header | `Upload Documents`, a description, breadcrumbs `Overview > Upload`. With a preset folder the breadcrumbs add `Folders` and the folder name (`UploadPage.tsx:164-167`) |
| Banners | An error alert and an info alert |
| Target selector | Two radio cards, `MinIO Source Bucket` and `Folder Directory` (`UploadPage.tsx:179-201`) |
| Source field | A select of every source, with name, bucket and connector count |
| Folder field | The preset badge, or a `Target folder` text input |
| Content type | Three radio cards, `Documents`, `Images` and `Markdown` (`UploadPage.tsx:256-276`) |
| Drop zone | A click or drop area. The hint reads `Accepted: {accept}. Max size 100MB per file.` (`UploadPage.tsx:305`) |
| File list | One row per chosen file with its size in MB and a `Remove` button |
| Submit | `Upload n File(s)`, disabled while submitting, while the list is empty, or when the source target has no source (`UploadPage.tsx:330-336`) |

## 4. State

| State | Initial value | Purpose |
|---|---|---|
| `targetType` | `"source"` | Which target the submit uses |
| `sources`, `loadingSources`, `selectedSourceId` | `[]`, `true`, `""` | The source list, filled by `listSources()` on mount (`UploadPage.tsx:47-57`) |
| `presetDir` | `location.state.directory ?? ""` | A folder passed by the browse page (`UploadPage.tsx:30`) |
| `directoryName` | `presetDir` | Never changes, see section 8 |
| `usePreset` | `!!presetDir` | Never changes, see section 8 |
| `newFolderName` | `""` | The folder name for the legacy path |
| `contentType` | `"document"` | Chooses the file picker `accept` string only |
| `files` | `[]` | The chosen file list |
| `submitting`, `error`, `info`, `dragOver` | `false`, `null`, `null`, `false` | Request state and banners |

The page polls nothing. The source list loads once per session, because `AppLayout` keeps the page mounted.

`effectiveDir` is `presetDir` when `usePreset` is true, else `newFolderName || directoryName` (`UploadPage.tsx:59`).

## 5. File Admission

`isBlocked` rejects a file in two ways (`UploadPage.tsx:20-25`):

1. The extension is in `BLOCKED_EXTENSIONS`: `mp4`, `mov`, `avi`, `mkv`, `webm`, `wmv`, `flv`, `mp3`, `wav`, `ogg`, `aac`, `flac`, `m4a`, `wma` (`UploadPage.tsx:7-10`).
2. The MIME type starts with `video/` or `audio/`.

A drop with blocked files sets a synthetic `422 FILE_TYPE_BLOCKED` error that names each blocked file, and adds only the admitted files to the list (`UploadPage.tsx:62-76`). An admitted file can be removed again before submit (`UploadPage.tsx:78-80`).

The content type radios do not filter anything on the server. They set `input.accept` on the file picker and the hint text (`UploadPage.tsx:294`, `UploadPage.tsx:305`):

| Card | `accept` |
|---|---|
| Documents | `.pdf,.doc,.docx,.txt,.csv,.json,.xml,.html,.htm` |
| Images | `.png,.jpg,.jpeg,.gif,.webp,.bmp,.tiff,.svg` |
| Markdown | `.md,.mdx,.rst,.txt` |

The `Max size 100MB per file` text is a hint only. There is no client-side size check, and the server sets no size limit on the source path (section 7).

## 6. The Two Upload Flows

### 6.1 Source target — the default

1. The submit requires a source. Without one it sets `400 SOURCE_REQUIRED` and stops (`UploadPage.tsx:88-93`).
2. The page sets its info text to `Uploading files directly to selected MinIO source bucket...`.
3. It uploads the files one at a time in a loop (`UploadPage.tsx:96-101`).
4. `uploadSourceFile` builds a `FormData` with one `file` part and posts to `/api/sources/{id}/files` (`api.ts:1737-1745`).
5. On success it reports `Successfully uploaded n file(s) to MinIO source bucket '{name}'.` and navigates to `/sources/{id}` after 1200 ms (`UploadPage.tsx:103-106`).
6. On a failure it shows the `ApiError` or a synthetic `500 UPLOAD_FAILED` (`UploadPage.tsx:107-109`).

The loop stops at the first failure, so a failure after 3 of 5 files leaves 3 objects in the bucket and reports an error. The info text is not updated in that case.

Server behaviour (`sources.py:806-883`): every part named `file` or `files` is read with `await upload.read()` into memory, the name is passed through `sanitize_file_name`, and the bytes go to `put_object`. A local filesystem source writes to `storage/local_sources/<folder>` instead. An empty object list raises `422 EMPTY_FILE`. A successful call recomputes `total_files` and `total_size_bytes` and triggers a background fanout sync.

### 6.2 Folder target — the legacy chunked path

1. The directory name is `effectiveDir.trim().toLowerCase()` (`UploadPage.tsx:116`).
2. An empty name makes the handler return at once. It shows no message, and the button looks dead (`UploadPage.tsx:117`).
3. The info text becomes `Uploading — files will sync in the background.`
4. For every file, `uploadFileChunked(dir, file)` runs three steps (`api.ts:92-129`):
   * `POST /api/uploads/init` with `directory_name`, `file_name`, `total_chunks`, `total_size`, `mime_type` and `client_content_hash`. The hash is the SHA-256 of the file, from `computeFileHash` (`api.ts:97`, `api.ts:99-110`).
   * `PUT /api/uploads/{upload_id}/chunks/{i}` for every 5 MiB slice. `CHUNK_SIZE` is 5 MiB (`api.ts:11`, `api.ts:112-124`). This request uses a raw `fetch` with no `X-API-Key` header (`api.ts:119-122`).
   * `POST /api/uploads/{upload_id}/complete` (`api.ts:126-128`).
5. The result status counts one of two ways: `duplicate` increments the duplicate count, anything else increments the queued count (`UploadPage.tsx:130-132`).
6. A per-file `422 CORRUPTION_DETECTED` is collected and the loop continues. Any other error aborts the loop and skips the navigation (`UploadPage.tsx:133-139`, `UploadPage.tsx:151-153`).
7. The info text joins the parts that are non-zero: `n queued for sync`, `n duplicates skipped`, `n corrupted file(s) failed integrity check` (`UploadPage.tsx:141-147`).
8. The page navigates to `/browse/{dir}` after 1500 ms (`UploadPage.tsx:148-150`).

The `complete` step stitches the chunks, validates the content type from magic bytes, verifies the SHA-256, and checks for a duplicate in the folder. It creates the folder workspace when the folder does not exist yet (`file_manager/core/service.py:60`). A duplicate stores a duplicate record and returns `status: "duplicate"` with no job (`service.py:64-84`).

## 7. Validation and Behaviour Limits

| Rule | Value | Source |
|---|---|---|
| Client block list | 14 media extensions, plus any `video/` or `audio/` MIME type | `UploadPage.tsx:7-10`, `UploadPage.tsx:20-25` |
| Client size limit | None. The `100MB` text is a hint | `UploadPage.tsx:305` |
| Source file field | `file` or `files`, repeated | `sources.py:817-821` |
| Source file failure on an empty body | `422 FILE_REQUIRED`, or `422 EMPTY_FILE` when no part holds data | `sources.py:824-825`, `sources.py:869-870` |
| Source file size limit | None. The whole file is read into memory | `sources.py:862-866` |
| Object key | The uploaded name after `sanitize_file_name`, with no folder prefix | `sources.py:865` |
| Upload directory | 1 to 64 characters | `uploads.py:16` |
| Upload file name | 1 to 512 characters | `uploads.py:17` |
| Chunk count | 1 or more | `uploads.py:18` |
| Declared size | 1 byte or more | `uploads.py:19` |
| Client hash | Exactly 64 characters. It is the SHA-256 of the file | `uploads.py:21` |
| Empty chunk body | `422 EMPTY_CHUNK` | `uploads.py:54` |
| Chunk size | 5 MiB, from `CHUNK_SIZE` | `api.ts:11` |
| Complete | `202` with `file_id`, `job_id`, `status` and the hash fields | `service.py:21-84` |
| Other server checks | `INVALID_CHUNK_COUNT`, `INVALID_FILE_SIZE`, `MISSING_CONTENT_HASH`, `SIZE_MISMATCH`, `FILE_TYPE_BLOCKED`, `CORRUPTION_DETECTED` | `chunks.py:27-32`, `chunks.py:107-111`, `service.py:21-84` |

## 8. Dead or Unreachable Code and Defects

| Finding | Detail | Source |
|---|---|---|
| Both setters of the folder state are unused | `_setDirectoryName` and `_setUsePreset` are declared and never called. `directoryName` therefore keeps its initial value `presetDir`, and `usePreset` keeps `!!presetDir`. Both values are constants for the life of the page | `UploadPage.tsx:37-38` |
| The `directoryName` fallback is dead | `effectiveDir` reads `newFolderName || directoryName`, but `directoryName` is `""` on every path that reaches the expression. The `|| directoryName` branch never contributes | `UploadPage.tsx:59` |
| The folder name input is not stored | The preset branch and the input branch are exclusive, and the input writes `newFolderName` only | `UploadPage.tsx:235-250` |
| An empty folder name fails silently | The handler returns before it sets any message, so the submit button appears broken | `UploadPage.tsx:117` |
| The chunk request sends no API key | The raw `fetch` for a chunk carries no `X-API-Key` header. With a key configured the `PUT` answers 401 and the upload aborts `[INFERENCE]` on the status code | `api.ts:119-122` |
| The drop zone is not keyboard reachable | The zone is a plain `div` with `onClick`, no `role`, no `tabIndex` and no key handler. The file input is created on demand and never enters the DOM | `UploadPage.tsx:278-297` |
| The filename hint does not filter | `Max size 100MB per file` is never enforced here or on the source route | `UploadPage.tsx:305`, `sources.py:862-866` |
| A partial source upload is not reported | The loop aborts on the first error after some files are already stored | `UploadPage.tsx:96-109` |

## 9. What the Page Does Not Do

* No progress bar and no per-file status. One info line covers the whole batch.
* No cancel.
* No folder creation outside the legacy path. The source target writes to the bucket root only.
* No connector choice and no pipeline choice.
* No size check, and no file-type check on the server for the source path. The block list is client-side only.
* No re-read of the source list after a navigation, because the page stays mounted for the session.
