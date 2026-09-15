# Folders & File Browser Page

## Route
`/browse`

## Component
`BrowsePage.tsx` / `DirectoryPage.tsx` / `FileViewerPage.tsx`

## Features
Provides S3/MinIO bucket exploration capabilities:
- **MinIO Source Selector**: Dropdown to select an active data source bucket (e.g., `source-v-res-5d2edc8f`).
- **File Explorer**: Lists raw files synced into the MinIO bucket. Displays item counts and allows refreshing the bucket structure.
- **File Viewer**: A sub-route feature (`/browse/:name/view/:fileId`) that visualizes the content of a specific indexed file directly from object storage.

## Backend APIs Used
- `GET /api/directories/{name}/files`
- `GET /api/sources/{source_id}/files`
- `GET /api/files/{file_id}` 