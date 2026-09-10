# 05. Document Upload Page (`/upload`)

## 1. Page Purpose & Summary

The **Document Upload** (`/upload`) page provides an enterprise-grade, resumable chunked file uploader capable of ingesting large documents (PDFs, DOCX, TXT, Markdown, CSV, JSON) up to multi-gigabyte sizes without memory overflow or HTTP request timeouts.

---

## 2. Resumable 5MB Chunked Ingestion Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 5MB CHUNKED UPLOAD PIPELINE                                 │
├─────────────────────────────────────────────────────────────────────────────────────────────┤
│ 1. Client computes SHA256 file hash & slices file into 5MB chunks                           │
│ 2. POST /api/uploads/init         -> Returns upload_id & upload session metadata            │
│ 3. Loop PUT /api/uploads/:id/chunks/:i -> Streams chunk 0..N to MinIO staging area          │
│ 4. POST /api/uploads/:id/complete -> Assembles chunks in MinIO & creates file record        │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Key UI Modules & Features

1. **Drag-and-Drop Dropzone**: Interactive upload surface supporting single file or multi-file batch uploads.
2. **Target Directory Folder / Source Selector**: Dropdown to specify which virtual directory folder or data source bucket will receive the uploaded files.
3. **Upload Progress List**: Real-time progress bar per file displaying upload speed (MB/s), chunk percentage, SHA256 calculation status, and retry controls.
4. **Supported Format Badges**: Visual indicators for PDF, DOCX, TXT, MD, CSV, JSON file formats.

---

## 4. Data Fetching & API Interactions

- **`initiateUpload(payload)`**: `POST /api/uploads/init` — Starts upload session with file name, size, MIME type, SHA256 hash, and target directory. Returns `upload_id`.
- **`uploadChunk(uploadId, index, chunkData)`**: `PUT /api/uploads/{uploadId}/chunks/{index}` — Stores chunk byte payload in MinIO staging location (`uploads/{upload_id}/chunks/{index}`).
- **`completeUpload(uploadId)`**: `POST /api/uploads/{uploadId}/complete` — Concatenates staging chunks into final MinIO object location and writes `FileRecord` into PostgreSQL.
