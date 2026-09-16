# 05 — Document Upload & Staging Manager

## 1. Executive Summary & Page Purpose
The **Document Upload & Staging Manager** (`UploadPage.tsx` and upload modal workflows across `BrowsePage.tsx` and `SourcesPage.tsx`) handles multi-format document ingestion from client web browsers into MinIO object storage buckets. It provides client-side drag-and-drop file ingestion, file integrity validation (SHA-256 deduplication), format parsing (PDF, DOCX, TXT, JSON, MD, CSV), and automatic post-upload indexing.

---

## 2. Supported Formats & Parsing Engine

| Format | Extension | Extractor Engine | Parsing Strategy |
|---|---|---|---|
| **PDF** | `.pdf` | `pypdf` / `pdfplumber` / OCR fallback | Text stream extraction, table preservation, metadata harvesting |
| **Word** | `.docx`, `.doc` | `python-docx` | Heading hierarchy, paragraph structure, inline tables |
| **Markdown** | `.md`, `.markdown` | Python `markdown` / AST parser | Semantic section headers, code fence preservation |
| **Plain Text** | `.txt`, `.log` | UTF-8 Stream Parser | Fixed/Sliding window chunking with sentence boundary preservation |
| **Structured** | `.json`, `.csv` | `json` / `pandas` | Key-value flattening, row-based serialization for embedding |

---

## 3. Upload & Ingestion Flow

```
+-------------------------------------------------------------------------------+
|  User Browser: Drag & Drop Files (PDF, DOCX, TXT, MD, JSON)                   |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|  1. SHA-256 Checksum Calculation & File Type Validation                       |
|     - Detect duplicates in target MinIO bucket / directory                    |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|  2. Direct Multipart Streaming to Backend (`POST /api/uploads/file`)          |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|  3. MinIO S3 Object Store Placement (`s3://<bucket>/<file_key>`)               |
|     - Metadata DB Record Creation (`FileRecord`, `Directory`)                 |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|  4. Async Document Parsing & Chunking Pipeline                                |
|     - Recursive text splitter (chunk size: 500 tokens, overlap: 50 tokens)    |
|     - Store chunk metadata in SQLite / PostgreSQL                             |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|  5. Knowledge Store Fanout Trigger (Optional Auto-Sync)                       |
+-------------------------------------------------------------------------------+
```

---

## 4. Backend APIs & Contracts

| Method | Endpoint | Description | Request / Response |
|---|---|---|---|
| `POST` | `/api/uploads/file` | Uploads a single document file to MinIO staging | `Multipart Form` -> `UploadFileResponse` |
| `POST` | `/api/uploads/batch` | Uploads multiple files in parallel | `Multipart Form` -> `BatchUploadResponse` |
| `POST` | `/api/sources/{source_id}/upload` | Uploads directly into a specific MinIO source bucket | `Multipart Form` -> `SourceFileEntry` |
| `GET` | `/api/uploads/status/{task_id}` | Polls async parsing and chunking progress | `UploadTaskStatus` |

### Sample Response (`POST /api/uploads/file`)
```json
{
  "id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "filename": "resume_alex_chen.pdf",
  "size": 49356,
  "content_type": "application/pdf",
  "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "bucket": "v-res",
  "key": "resumes/resume_alex_chen.pdf",
  "status": "ready",
  "chunks_count": 8
}
```
