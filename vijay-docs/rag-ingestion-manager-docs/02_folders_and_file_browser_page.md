# 02. Folders & Directory File Browser Page (`/browse`)

## 1. Page Purpose & Summary

The **Folders & File Browser** (`/browse`) page allows administrators to navigate the virtual directory hierarchy stored inside MinIO S3 buckets and PostgreSQL metadata tables. It supports file inspection, search filtering, virtual folder creation, inline file renaming, and file deletion.

---

## 2. Key UI Modules & Features

1. **Virtual Directory Navigation Tree**: Sidebar/grid view listing root directory folders (`name`, `file_count`, `updated_at`).
2. **Directory File List Table**: Displays files within the selected folder with metadata columns:
   - File Name & File ID
   - SHA256 Hash
   - Storage Size (formatted in KB/MB)
   - Content Type / MIME Type
   - Action Buttons (Rename, Delete, Download).
3. **Directory Creation Modal**: Dialog for creating a new named virtual directory folder.
4. **File Search & Filter Bar**: Instant client-side text filter by file name or extension.

---

## 3. Data Fetching & API Interactions

- **`listDirectories()`**: `GET /api/directories`
  - Returns array of `DirectorySummary` objects (`id`, `name`, `file_count`, `created_at`).
- **`listDirectoryFiles(directoryName)`**: `GET /api/directories/{name}/files`
  - Returns array of `FileRecord` items contained inside the target directory.
- **`renameFile(fileId, newName)`**: `PATCH /api/files/{id}`
  - Modifies file display name in PostgreSQL database records.
- **`deleteFile(fileId)`**: `DELETE /api/files/{id}`
  - Permanently deletes file object from MinIO S3 and purges metadata from PostgreSQL.

---

## 4. Operational Invariants

- Deleting a file from `/browse` immediately invalidates any knowledge store indexing tasks referencing that file hash.
- Folder names are sanitized to prevent S3 key path traversal vulnerabilities.
