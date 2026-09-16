# 02 — Folders & File Browser Page

## 1. Executive Summary & Page Purpose
The **Folders & File Browser Page** (`BrowsePage.tsx`, route: `/browse` and `DirectoryPage.tsx`, route: `/browse/:id`) provides a comprehensive document exploration, inspection, and verification interface. It enables users to browse raw files stored in MinIO buckets and virtual workspace directories, view rich document content (Markdown, raw text, and metadata), and inspect chunk-level partitioning and extraction quality before Knowledge Store fanout sync.

---

## 2. UI Layout & Visual Components

```
+----------------------------------------------------------------------------------------------------+
|  Folders & File Browser                                                                            |
|  Select Source / Bucket: [ v-res (MinIO Connector) v ]     Search: [ Filter files... ]             |
+----------------------------------------------------------------------------------------------------+
|  File List (v-res)                                 |  Document Content Viewer & Inspector          |
|  ------------------------------------------------- |  -------------------------------------------  |
|  📄 resume_alex_chen.pdf       (48.2 KB)  [Select] |  Mode: [ Preview | Raw Text | Metadata ]     |
|  📄 resume_sarah_connor.docx   (52.1 KB)           |                                               |
|  📄 resume_elena_rostova.pdf   (44.9 KB)           |  ## Alex Chen — Senior AI Engineer            |
|  📄 resume_marcus_vance.pdf    (46.0 KB)           |  **Location**: San Francisco, CA              |
|  📄 resume_devon_lane.pdf      (41.3 KB)           |  **Skills**: PyTorch, Qdrant, Neo4j, Fast...  |
|  📄 resume_priya_sharma.pdf    (49.8 KB)           |                                               |
|  📄 resume_liam_o_connor.pdf   (43.7 KB)           |  -------------------------------------------  |
|  📄 resume_aisha_patel.pdf     (47.4 KB)           |  Extracted Chunks: 8 | SHA-256 Verified       |
|  📄 resume_carlos_mendez.pdf   (45.1 KB)           |  [ Download Raw ]  [ Inspect Chunks ]         |
|  📄 resume_jordan_hayes.pdf    (42.8 KB)           |                                               |
+----------------------------------------------------------------------------------------------------+
```

### Component Breakdown
1. **Source / Bucket Selector**: Dropdown to toggle between registered MinIO connector sources (`v-res`), manual upload sources (`manual-vj`), and workspace directories.
2. **Search & Filter Bar**: Instant client-side filtering by filename, extension, or modification date.
3. **File List Panel**: Displays document name, file size (formatted via `formatBytes`), and last modified timestamp with active selection highlighting.
4. **Multi-Mode Document Inspector**:
   - **Preview Mode**: Renders extracted text using `MarkdownMessage.tsx` with Markdown styling, code highlights, and tables.
   - **Raw Text Mode**: Displays verbatim unparsed text extraction.
   - **Metadata Mode**: Shows technical metadata, including MinIO ETag, content type, chunk count, file size, SHA256 checksum, and parsing status.

---

## 3. Backend APIs & Data Contracts

| Method | Endpoint | Description | Response Model |
|---|---|---|---|
| `GET` | `/api/sources/{source_id}/files` | Lists files stored in the source MinIO bucket | `list[SourceFileEntry]` |
| `GET` | `/api/sources/{source_id}/files/{file_key}/content` | Fetches extracted/raw content of a document | `{"content": str, "file_key": str}` |
| `GET` | `/api/sources/{source_id}/files/{file_key}/download` | Direct presigned stream to download original binary | `Binary Stream` |
| `GET` | `/api/directories/{dir_id}` | Retrieves directory details and file hierarchy | `DirectoryDetailResponse` |
| `DELETE` | `/api/sources/{source_id}/files/{file_key}` | Deletes a file from MinIO and metadata database | `{"status": "deleted"}` |

### Sample Data Payload (`SourceFileEntry`)
```json
{
  "key": "resumes/resume_alex_chen.pdf",
  "name": "resume_alex_chen.pdf",
  "size": 49356,
  "last_modified": "2026-09-16T08:35:12.000Z",
  "content_type": "application/pdf",
  "etag": "\"d41d8cd98f00b204e9800998ecf8427e\"",
  "source_id": "2da1c0d5-5727-4632-9cb9-009c91d4e0e4",
  "chunks_count": 8,
  "status": "indexed"
}
```

---

## 4. Key Workflows & User Operations
1. **Document Selection & Preview**: Clicking any file in the left pane triggers an async fetch to `/api/sources/{id}/files/{key}/content`, updating the preview pane without full-page reloads.
2. **Quality Verification**: Engineers inspect the parsed markdown representation to verify that tables, bullet points, headers, and contact information were accurately extracted before running fanout embeddings.
3. **Direct File Downloads**: The "Download Raw" action requests presigned URLs from MinIO to retrieve original unmodified binaries (PDF, DOCX, etc.).
