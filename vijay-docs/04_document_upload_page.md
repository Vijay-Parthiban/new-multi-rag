# Page Documentation: Document Upload & Multi-Format Ingestion (`UploadPage.tsx`)

## 1. Overview & Purpose

The **Document Upload & Ingestion Engine** (`/upload`) enables users to drag and drop multi-format files (PDF, DOCX, TXT, Markdown, HTML, CSV, JSON), assign processing pipeline targets, select extraction modes (including OCR for scanned documents), and trigger asynchronous background indexing into MinIO storage and Qdrant vector collections.

---

## 2. Component Structure & Workflow

1. **Upload Dropzone (`UploadPage.tsx`)**: Drag-and-drop zone supporting file browser selection, file validation, and format detection.
2. **Target Pipeline Selector**: Specifies which RAG Pipeline (and corresponding Qdrant vector collection) should receive the chunk embeddings.
3. **Processing Options Selector**: Configures document parser settings (Fast Text Extraction, Layout-Aware Parsing, OCR for Scanned Images/PDFs).
4. **Ingestion Queue Progress Tracker**: Live progress indicators tracking file upload, MinIO persistence, Celery background chunking, embedding generation, and Qdrant upsert.

---

## 3. Visual Layout Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Header: Document Upload & Ingestion                                         │
│ Subtitle: Direct multi-format file ingestion into RAG vector collections    │
├─────────────────────────────────────────────────────────────────────────────┤
│ Target Pipeline Configuration:                                              │
│ Target Pipeline: [Default Vector Pipeline (qdrant: rag-documents) ▾]       │
│ Extraction Mode:  (●) Standard Text  ( ) OCR Layout-Aware  ( ) Fast Raw    │
├─────────────────────────────────────────────────────────────────────────────┤
│ Drag & Drop Upload Zone:                                                    │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │                             📁                                          │ │
│ │               Drag & Drop Files Here or Click to Browse                 │ │
│ │  Supported formats: PDF, DOCX, TXT, MD, HTML, CSV, JSON (Up to 100 MB) │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────────────┤
│ Ingestion Progress Queue:                                                   │
│ 📄 quarterly_report_2026.pdf (4.2 MB)  [████████████████████ 100%] SYNCED   │
│ 📄 product_roadmap.md (18 KB)          [████████████████████ 100%] SYNCED   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. API Endpoints & Multi-Part Request Contract

### 4.1 `POST /api/upload`
- **Content-Type**: `multipart/form-data`
- **Form Fields**:
  - `file`: Binary file payload
  - `pipeline_id`: Target pipeline identifier (e.g. `pipe-001`)
  - `ocr_enabled`: Boolean string (`true`/`false`)
  - `directory`: Destination storage bucket/directory (`rag-raw-documents`)

- **Response Schema**:
```json
{
  "status": "success",
  "task_id": "celery-task-9901-ab88",
  "file_id": "file-8891",
  "filename": "quarterly_report_2026.pdf",
  "bucket": "rag-raw-documents",
  "size": 4404019,
  "message": "File uploaded successfully. Processing queued."
}
```

---

## 5. Ingestion Pipeline Lifecycle

```
[User Dropzone]
      │ (Multipart File Upload)
      v
[Ingestion API :8007] ──────► Store Raw File ──────► [MinIO Storage :9000]
      │
      ├──────────────────────► Enqueue Task ─────────► [Redis Queue :6379]
      │                                                       │
      v                                                       v
[Client Progress] ◄────────── Query Status ────────── [Celery Worker]
                                                              │
                                            1. Extract Text & OCR
                                            2. Recursive Text Chunking
                                            3. OpenAI / Cohere Embedding
                                                              │
                                                              v
                                                    [Qdrant Collection]
```

---

## 6. How to Run & Test

1. **Navigate to Upload Page**: Open `http://localhost:5173/upload`.
2. **Select Target Pipeline**: Choose your configured pipeline (e.g., `Default Vector Pipeline`).
3. **Upload Files**: Drag a PDF or TXT file into the dropzone.
4. **Monitor Progress**: Observe real-time progress bars update from Uploading -> Processing -> Synced.
5. **Verify Indexing**: Navigate to `/browse` or `/chat` to search the newly uploaded content.
