# 05 — Document Upload (removed page) & File Format Support

**Last updated:** 2026-09-20

> **Status: the `/upload` page no longer exists.**
> The standalone **Document Upload & Staging Manager** (`frontend/src/pages/UploadPage.tsx`, route `/upload`, sidebar label "Upload") was removed on 2026-09-20. The nav item, the page mount in `AppLayout.tsx`, the Home page quick-link card, and the client helper `uploadFileChunked` were all deleted with it.
>
> Uploading is now done from the Sources page. See §1.1. The file-format and post-upload sections below are kept because they describe the shared parsing and indexing path, which is unchanged.

## 1. Executive Summary

### 1.1 Where uploads happen now

| Destination | Route | What it does |
|---|---|---|
| **Manual Upload Source** | `/sources` → New Source → *Manual Upload Source*, or the **Upload Files** action on a manual source card/row | Creates a dedicated MinIO bucket and opens `FileBrowser` straight away. The file picker or the dropzone writes each file into that bucket. |
| **Source bucket files** | `/sources/:id` → *Source Files* tab | Lists and deletes objects. Upload is enabled for `minio_manual` and legacy local sources only. |
| **Folder workspaces** | no UI | `POST /api/uploads/init` → `PUT .../chunks/{n}` → `POST .../complete` still exists in the backend, but nothing in the frontend calls it any more. Folder folders are read-only through `/browse/:name`. |

The removed page was the only caller of the chunked-upload client. Its content-type radios, client-side audio/video block list, and the display-only "Max size 100MB per file" hint went with it. `FileBrowser` has no extension block list, so a file rejected by the old page can now be uploaded to a source bucket.

### 1.2 What was deliberately kept

- All `POST/PUT /api/uploads/*` routes and the `file_manager` chunk service, because other clients may call them and the worker path is shared.
- `frontend/src/hash.ts` (`computeFileHash`), exported but no longer imported anywhere.
- `components/Sources/FileBrowser.tsx`, which is now the single upload surface.

Parsing for indexing lives in `backend/src/ingestion_service/core/page_yielder.py`; the UI never parses anything. Chunking and embedding settings belong to RAG pipelines and Knowledge Products, not to any upload surface.

---

## 2. Supported Formats & Parsing Engine

`iter_file_pages(path, mime_type, original_name)` (`page_yielder.py:18`) dispatches on suffix first, then MIME, and yields `FilePage(page_index, text, image_png)` one page at a time:

| Format | Branch | Extractor | Strategy |
|---|---|---|---|
| **PDF** | suffix `.pdf` or MIME `application/pdf` (`:23`) | PyMuPDF (`fitz`) | One page per PDF page; text via `get_text("text")` plus a 150 dpi PNG rendered into `image_png` for multimodal pipelines (`:54-68`) |
| **Word** | suffix `.docx` or the DOCX MIME (`:27`) | `python-docx` | All non-empty paragraphs joined with `\n\n` into a single page; an empty document still yields one empty page (`:70-80`) |
| **CSV** | suffix `.csv` or MIME `text/csv`/`application/csv` (`:31`) | `csv` module | Every row joined with `", "` and all rows joined with newlines into a single page (`:82-89`) |
| **JSON** | suffix `.json` or MIME `application/json` (`:35`) | `json` module | Top-level array → one page per item (`json.dumps` per item); object → one pretty-printed page; invalid JSON → the raw text as one page (`:91-105`) |
| **Markdown / text** | suffix `.md`, `.markdown`, `.txt`, `.log` or MIME starting `text/` (`:39`) | UTF-8 read (`errors="replace"`) | Single page with the whole file |
| **Anything else** | fallback (`:42-49`) | UTF-8 read | One page with a best-effort text read and a `page_yielder_fallback_utf8` warning log |

Consequences worth knowing:
- There is **no image, audio, video or OCR parser**. `.png/.jpg/.jpeg/.gif/.webp/.bmp/.tiff/.svg` and any other unknown suffix fall into the UTF-8 fallback, so they index as empty or binary-noise text.
- Only `.docx` is supported — legacy `.doc`, `.xls/.xlsx`, `.ppt/.pptx`, `.xml`, `.html`, `.rst` and `.mdx` have no dedicated branch and are read by the UTF-8 fallback.
- MIME is used as a secondary trigger, so a `.txt` file served as `application/pdf` would go through the PDF branch.

Tests: `backend/tests/test_page_yielder.py` covers plain text, JSON array splitting and CSV row joining.

---

## 3. Upload Paths

### 3.1 Source-bucket path (the only path the UI uses)

The file drawer calls `uploadSourceFiles(sourceId, files)` — multipart `POST /api/sources/{source_id}/files` with repeated `files` parts (`frontend/src/api.ts:1347`). Server side (`apps/api/routes/sources.py:836`):

1. `ensure_bucket(minio_bucket)`, then each non-empty file is written with `put_object` under its sanitized file name. Local-filesystem sources write to `storage/local_sources/<folder_name>` instead.
2. `_update_source_metrics` recomputes `total_files` / `total_size_bytes`.
3. `_trigger_sync_in_background` fires `_trigger_pipeline_syncs(db_session, db_source)`. That function does not run the fanout inline any more. It starts `sync_knowledge_product(product_id)` for every Knowledge Product linked to the source, then enqueues a sync run per linked pipeline. The product's own poller does the destination writes.

Deletes (`DELETE /files?key=…`) repeat steps 2–3.

### 3.2 Folder path (legacy chunked upload, no UI caller)

`POST /api/uploads/init` with `{directory_name, file_name, total_chunks, total_size, mime_type, client_content_hash}` → `PUT /api/uploads/{upload_id}/chunks/{i}` per 5 MiB chunk → `POST /api/uploads/{upload_id}/complete`, which stitches the chunks, validates the content type from magic bytes, verifies the SHA-256, and detects duplicates by content hash before enqueuing a `file_manager:jobs` job.

The removed page reported `N queued for sync`, `N duplicates skipped`, `N corrupted file(s) failed integrity check` and navigated to `/browse/{folder}`. The endpoints are unchanged; only the caller is gone.

---

## 4. Backend APIs & Contracts

| Method | Endpoint | Description | UI caller |
|---|---|---|---|
| `POST` | `/api/uploads/init` | Start a chunked upload session (201) | none |
| `PUT` | `/api/uploads/{upload_id}/chunks/{chunk_index}` | Upload one chunk (204) | none |
| `POST` | `/api/uploads/{upload_id}/complete` | Stitch, validate, verify hash, enqueue storage (202) | none |
| `POST` | `/api/sources/{source_id}/files` | Upload one or more files into the source bucket/folder (201) | `FileBrowser` |
| `DELETE` | `/api/sources/{source_id}/files` | Delete an object and re-trigger sync | `FileBrowser` |
| `GET` | `/api/sources/{source_id}/files/content` | File preview content | `FileBrowser` |
| `POST` | `/api/sources/{source_id}/sync` | Manual connector sync for a source | `SourcesPage` / `SourceDetailPage` |
| `POST` | `/api/sources/{source_id}/events` | MinIO bucket-notification webhook used for live monitoring | MinIO |

`InitUploadRequest` (`routes/uploads.py:15`): `directory_name` 1–64 chars, `file_name` 1–512 chars, `total_chunks ≥ 1`, `total_size ≥ 1`, optional `mime_type`, `client_content_hash` exactly 64 characters. Server-side validation (`file_manager/core/chunks.py`): `INVALID_CHUNK_COUNT`, `INVALID_FILE_SIZE`, `MISSING_CONTENT_HASH`, empty chunk body → `EMPTY_CHUNK`, stitched size ≠ declared `total_size` → `SIZE_MISMATCH`, blocked media MIME/extension → `FILE_TYPE_BLOCKED` (magic-byte check via `filetype`), SHA-256 mismatch → `CORRUPTION_DETECTED`. `complete` returns `{file_id, job_id, status: "processing"|"duplicate", content_hash, client_content_hash, hash_verified, duplicate_of_file_id?, duplicate_of_file_name?}`.

Auth: both services mount `verify_api_key` as an app-level dependency (`apps/api/main.py:36`, `shared-libs/platform-common/src/platform_common/auth.py`). The key may be sent as the `X-API-Key` header or the `api_key` query parameter; when no key is configured the check is a no-op; `/health`, `/docs`, `/openapi.json` and `/redoc` are always public.

### Frontend API client notes (`frontend/src/api.ts`)
- `authHeaders(API_KEY)` adds `X-API-Key` to `apiFetch` calls.
- `getSourceFileContentUrl()` and `getSourceFileContent()` pass `api_key` as a query parameter for authenticated previews.
- `API_URL` comes from `VITE_API_URL` (this repo's `.env`: `http://localhost:8007`).
- `CHUNK_SIZE` and `uploadFileChunked` were removed with the page. `computeFileHash` in `hash.ts` is now unreferenced.

---

## 5. What Happens After Upload: Chunking, Embedding and Indexing

Upload itself only stores bytes. Indexing happens later, on one of two paths:

**Path 1 — RAG pipeline sync (per linked pipeline).** The pipeline is enqueued by `_trigger_pipeline_syncs()`; the worker reads the source file and `ingestion_service/core/indexer.py` calls `chunk_text(text, pipeline.chunk_size, pipeline.chunk_overlap)` (`indexer.py:137`) where `chunk_text` is the recursive markdown/text splitter (`ingestion_service/utils/text_splitter.py:4`, splits on `^#+ ...` headings and blank lines, with word-level overflow splitting and overlap carried from the end of the previous chunk). Defaults from `apps/api/routes/pipelines.py:31-32`: `chunk_size = 1000` (allowed 100–8000), `chunk_overlap = 120` (allowed 0–2000); both are per-pipeline and settable on the Pipelines page.

**Path 2 — Knowledge Product fanout (per linked product).** The product poller calls `sync_knowledge_product()` and then `execute_universal_fanout_sync(db, product)`. The fanout reads each source object, calls `iter_file_pages()` and writes **one record per page**; it does not call `chunk_text`. It records its own state in `knowledge_product_files`, not in `IndexedFile`. See document 04 for the per-destination payloads.

Embedding defaults and dimension behaviour:
- Default embedding model `settings.embedding_model = nvidia-embed-passage`, called through the LiteLLM proxy at `LITELLM_BASE_URL` with `OPENAI_API_KEY`.
- `EmbeddingClient` (`ingestion_service/embeddings/client.py`) catches LiteLLM failures and falls back to FastEmbed `BAAI/bge-small-en-v1.5` (384-dimension vectors); a failed image embedding returns a zero vector of 384 floats.
- The Knowledge Product's Qdrant `vector_size` default is `2048`; `ensure_collection()` recreates the target collection when the stored dense vector size differs from the configured size (`shared-libs/platform-common/src/platform_common/vector/qdrant_store.py:71-116`). When a product config has no `vector_size`, the fanout uses the length of the first embedding instead.
- Uploading into a source triggers the fanout/pipeline sync in the background, but a product whose destinations are all paused, or a file whose ETag and size are unchanged since the last sync, is not re-indexed.

---

## 6. Navigation & Routes

| Path | Component | Description |
|---|---|---|
| `/browse` | `BrowsePage.tsx` | MinIO source buckets |
| `/browse/:name` | `DirectoryPage.tsx` | Browse the files of one upload folder workspace |
| `/browse/:name/view/:fileId` | `FileViewerPage.tsx` | Preview one stored file |
| `/sources` | `SourcesPage.tsx` | Manage NiFi and manual-upload buckets (see document 03) |
| `/sources/:id` | `SourceDetailPage.tsx` | One source: connectors, catalogue, files |
| `/knowledge-store` | `KnowledgeStorePage.tsx` | Knowledge Product list and creation (see document 04) |
| `/knowledge-store/:id` | `KnowledgeProductPage.tsx` | One Knowledge Product: destination cards, live fanout timeline, ingested files (see document 04) |

The sidebar (`components/AppLayout.tsx:12-17`) links Overview `/`, Folders `/browse`, Sources `/sources` and Knowledge Store `/knowledge-store`. There is no `/upload` route and no Upload nav item. `App.tsx` only holds legacy redirects: `/directories` → `/browse`, `/directories/:name` → `/browse/:name`, `/directories/:name/view/:fileId` → `/browse/:name/view/:fileId`.
