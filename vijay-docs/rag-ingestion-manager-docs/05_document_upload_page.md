# 05 — Document Upload & Staging Manager

**Last updated:** 2026-09-17

## 1. Executive Summary & Page Purpose
The **Document Upload & Staging Manager** (`UploadPage.tsx`, route: `/upload`) handles multi-format document ingestion from the browser into MinIO object storage buckets or virtual folder workspaces. It provides drag-and-drop upload, SHA-256 integrity validation, chunked transfer with API key auth on each chunk, and post-upload availability for Knowledge Store fanout sync.

The Upload page is linked from the sidebar navigation and the Overview dashboard quick links.

---

## 2. Supported Formats & Parsing Engine

Parsing is implemented in `src/ingestion_service/core/page_yielder.py` (`iter_file_pages`):

| Format | Extension / MIME | Extractor | Strategy |
|---|---|---|---|
| **PDF** | `.pdf`, `application/pdf` | PyMuPDF (`fitz`) | One page per yield; optional page PNG for multimodal |
| **Word** | `.docx` | `python-docx` | Paragraph text joined into a single document page |
| **CSV** | `.csv`, `text/csv` | `csv` module | Rows serialized as comma-separated lines |
| **JSON** | `.json` | `json` module | Array items yield one page each; objects yield formatted JSON |
| **Markdown / Text** | `.md`, `.txt`, `.log`, `text/*` | UTF-8 read | Single page with full file content |
| **Unknown** | other | UTF-8 fallback | Logged warning; best-effort text read |

Unit tests: `backend/tests/test_page_yielder.py`

---

## 3. Upload & Ingestion Flow

```
+-------------------------------------------------------------------------------+
|  User Browser: Drag & Drop Files (PDF, DOCX, TXT, MD, JSON, CSV)              |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|  1. SHA-256 Checksum Calculation & File Type Validation                       |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|  2. Chunked Upload to Backend                                               |
|     POST /api/uploads/init  ->  PUT /api/uploads/{id}/chunks/{n} (auth hdr) |
|     ->  POST /api/uploads/{id}/complete                                     |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|  3. MinIO S3 Object Store Placement (`s3://<bucket>/<file_key>`)               |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|  4. Knowledge Store Fanout (manual or scheduled sync on linked profile)       |
|     page_yielder -> embed -> parallel fanout to 5 sinks                       |
+-------------------------------------------------------------------------------+
```

---

## 4. Backend APIs & Contracts

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/uploads/init` | Start chunked upload session |
| `PUT` | `/api/uploads/{id}/chunks/{n}` | Upload one chunk (requires `X-API-Key` when auth enabled) |
| `POST` | `/api/uploads/{id}/complete` | Stitch, verify hash, enqueue storage job |
| `POST` | `/api/sources/{source_id}/upload` | Upload directly into a source bucket |

### Frontend API client notes (`frontend/src/api.ts`)
- Chunk PUT requests include `authHeaders(API_KEY)`.
- `getSourceFileContentUrl()` and `getSourceFileContent()` pass `api_key` query param for authenticated file preview.

---

## 5. Navigation & Routes

| Path | Component | Description |
|---|---|---|
| `/upload` | `UploadPage.tsx` | Primary upload UI |
| `/browse/:name` | `DirectoryPage.tsx` | Browse uploaded files in a folder workspace |
| `/sources` | `SourcesPage.tsx` | Manage buckets and connector-backed sources |

Legacy redirects: `/directories/*` → `/browse/*`
