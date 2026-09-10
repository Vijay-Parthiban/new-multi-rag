# 02. Folders & Directory File Browser Page (`/browse`)

## 1. Page Purpose & Summary

The **Folders & Directory File Browser** (`/browse`) page provides interactive navigation of the virtual directory hierarchy stored within PostgreSQL metadata and MinIO S3 object storage. Administrators can browse folders, view document details, perform client-side text filtering, create directories, rename files, and delete documents.

---

## 2. Key UI Modules & Features

1. **Virtual Directory Navigation Sidebar / Grid**: Lists top-level folders with document counts and creation timestamps.
2. **Directory File List Table**: Displays files within the active folder:
   - File Name & Unique File ID
   - SHA256 Content Hash
   - Storage Size (formatted KB/MB)
   - MIME / Content Type
   - Inline Actions: Download, Rename, Delete File.
3. **Directory Creation Modal**: Dialog for creating a new named virtual directory folder.
4. **File Search & Extension Filter**: Instant client-side text filter by file name or extension.

---

## 3. Data Fetching & API Interactions

- **`listDirectories()`**: `GET /api/directories` — Fetches virtual directory summary objects (`id`, `name`, `file_count`, `created_at`).
- **`listDirectoryFiles(directoryName)`**: `GET /api/directories/{name}/files` — Returns file records contained in the specified folder.
- **`renameFile(fileId, newName)`**: `PATCH /api/files/{id}` — Updates file display name in PostgreSQL.
- **`deleteFile(fileId)`**: `DELETE /api/files/{id}` — Deletes file object from MinIO S3 and removes metadata record from PostgreSQL.

---

## 4. Operational & Storage Invariants

- Virtual directory names are sanitized (`sanitize_directory_name`) to prevent invalid path sequences or key collision in MinIO S3.
- Document deletions cleanly purge object bytes from MinIO and cascade metadata deletions in PostgreSQL.
