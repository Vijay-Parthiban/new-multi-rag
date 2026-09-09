# 05. Document Upload Page (`/upload`)

## 1. Page Purpose & Summary

The **Document Upload** (`/upload`) page provides an enterprise-grade, resumable chunked file uploader capable of handling large documents (PDFs, DOCX, TXT, Markdown, CSV, JSON) up to multi-gigabyte sizes without memory overflow or HTTP request timeout.

---

## 2. Chunked Ingestion Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 5MB CHUNKED UPLOAD PIPELINE                                 │
├─────────────────────────────────────────────────────────────────────────────────────────────┤
│ 1. Client computes SHA256 file hash & slices file into 5MB chunks                           │
│ 2. POST /api/uploads/init         -> Returns unique upload_id & session metadata            │
│ 3. Loop PUT /api/uploads/:id/chunks/:i -> Uploads chunk 0..N sequentially or in parallel   │
│ 4. POST /api/uploads/:id/complete -> Assembles chunks in MinIO & creates file record        │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Key UI Modules & Features

1. **Drag-and-Drop Dropzone**: Interactive upload box supporting single or batch file drops.
2. **Target Folder / Source Selector**: Dropdown to choose which directory folder or data source bucket will receive the uploaded document.
3. **Upload Progress List**: Real-time progress bar per file displaying speed (MB/s), chunk percentage, SHA256 calculation status, and retry controls.
4. **Supported Format Badges**: Visual indicators for PDF, DOCX, TXT, MD, CSV, JSON formats.

---

## 4. Data Fetching & API Interactions

- **`initiateUpload(payload)`**: `POST /api/uploads/init`
  - Payload: `{ filename, file_size_bytes, content_type, sha256_hash, target_directory }`.
- **`uploadChunk(uploadId, chunkIndex, blob)`**: `PUT /api/uploads/{id}/chunks/{chunkIndex}`
  - Uploads raw 5MB byte chunk multipart body.
- **`completeUpload(uploadId)`**: `POST /api/uploads/{id}/complete`
  - Triggers MinIO multipart assembly and triggers downstream indexing workers.
