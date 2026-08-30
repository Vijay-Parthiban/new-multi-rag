# Page Documentation: Folders, Directory Browser & File Viewer (`BrowsePage.tsx`, `DirectoryPage.tsx`, `FileViewerPage.tsx`)

## 1. Overview & Purpose

The **Folders & File Browser Ecosystem** provides document storage exploration, directory tree navigation, and document contents inspection across all MinIO object storage buckets. Users can browse virtual directory structures, filter files, view vector status, preview document contents (PDFs, Markdown, TXT, JSON), and inspect chunk metadata.

---

## 2. Component Structure & Routes

1. **`BrowsePage.tsx`** (`/browse`): Master directory listing showing all available storage buckets and directories (`rag-raw-documents`, `source-*` buckets).
2. **`DirectoryPage.tsx`** (`/browse/:name`): Directory file browser displaying hierarchical folders and files within a specific bucket.
3. **`FileViewerPage.tsx`** (`/browse/:name/view/:fileId`): Split-pane document viewer featuring in-browser file preview, metadata panel, vector chunk points list, and deletion options.

---

## 3. Visual Layout Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Directory Header: Overview > Folders > engineering-docs                      │
│ Title: engineering-docs Bucket | Bucket Tag: rag-raw-documents               │
├─────────────────────────────────────────────────────────────────────────────┤
│ Search & Controls Bar:                                                      │
│  [🔍 Search files...    ] [Filter: All Files ▾] [View: 🌳 Tree | 📋 Flat]     │
├─────────────────────────────────────────────────────────────────────────────┤
│ File List / Tree View Table:                                                │
│  ┌── Name ───────────────────┬── Size ────┬── Type ──┬── Vector Status ──┐   │
│  │ 📁 architecture/         │ --        │ Folder   │ --               │   │
│  │ 📄 system_spec_2026.pdf   │ 2.4 MB    │ PDF      │ ● SYNCED (85 ch) │   │
│  │ 📄 README.md              │ 14 KB     │ Markdown │ ● SYNCED (4 ch)  │   │
│  └───────────────────────────┴───────────┴──────────┴──────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### File Viewer Split-Pane View (`FileViewerPage.tsx`)
```
┌──────────────────────────────────────┬──────────────────────────────────────┐
│ Document Preview Pane (Left)         │ Metadata & Chunk Details (Right)     │
│ ┌──────────────────────────────────┐ │ 📄 File: system_spec_2026.pdf         │
│ │ PDF / Markdown Rendered Content  │ │ 💾 Size: 2.4 MB | Type: PDF          │
│ │                                  │ │ 🪣 Bucket: rag-raw-documents         │
│ │ "Multi-RAG Platform Architecture │ │ ⏱️ Uploaded: 2026-08-30 10:15        │
│ │  specifies dual-vector..."       │ │                                      │
│ └──────────────────────────────────┘ │ 🔮 Vector Chunks (85):               │
│                                      │  [Chunk 1: 512 tokens - Qdrant #101] │
│                                      │  [Chunk 2: 480 tokens - Qdrant #102] │
└──────────────────────────────────────┴──────────────────────────────────────┘
```

---

## 4. API Endpoints & Data Contracts

### 4.1 `GET /api/directories`
- **Description**: Lists all active buckets and root storage directories.

### 4.2 `GET /api/directories/:name/files`
- **Description**: Returns all files within a specified directory bucket.
- **Response Schema (`DirectoryFilesResponse`)**:
```json
{
  "directory": "engineering-docs",
  "bucket": "rag-raw-documents",
  "files": [
    {
      "id": "file-8891",
      "filename": "system_spec_2026.pdf",
      "filepath": "architecture/system_spec_2026.pdf",
      "size": 2516582,
      "content_type": "application/pdf",
      "status": "synced",
      "chunk_count": 85,
      "uploaded_at": "2026-08-30T10:15:00Z"
    }
  ]
}
```

### 4.3 `GET /api/files/:id` & `GET /api/files/:id/chunks`
- **Description**: Fetches document metadata, presigned MinIO URL, and extracted Qdrant vector chunks.

---

## 5. How to Run & Verify

1. **Upload Test Files**: Use the Upload Page or API to ingest sample PDF/TXT files into MinIO.
2. **Navigate to Folders**: Open `http://localhost:5173/browse`.
3. **Verify Directory Browsing**: Click a folder to enter `DirectoryPage` (`http://localhost:5173/browse/rag-raw-documents`).
4. **Test Document Viewer**: Click any file to open `FileViewerPage`. Confirm file content renders on the left panel and vector chunks display on the right panel.
