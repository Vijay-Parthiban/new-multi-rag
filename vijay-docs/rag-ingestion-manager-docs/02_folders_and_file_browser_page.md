# Folders & File Browser Page

## Route
`/browse`

## Component
`BrowsePage.tsx` / `DirectoryPage.tsx` / `FileViewerPage.tsx`

## Features

Provides S3/MinIO bucket exploration for raw files synced into source buckets.

- **MinIO Source Selector**: Dropdown selecting an active data source bucket (e.g. `source-v-res-5d2edc8f`).
- **File Explorer**: Lists raw files synced into the MinIO bucket. Displays item counts and refreshes bucket structure on demand.
- **File Viewer**: Sub-route (`/browse/:name/view/:fileId`) renders content of a specific indexed file directly from MinIO object storage.
- **Legacy Redirect**: `/directories/:name` redirects to `/browse/:name` for backward compatibility.

## Active MinIO Buckets

| Source Name | Bucket |
|-------------|--------|
| v-res       | source-v-res-5d2edc8f |
| manual-vj   | source-manual-vj-5f4d24f4 |

Access MinIO Console directly at `http://localhost:9001` (user: `minioadmin`, password: `minioadmin`).

## Backend APIs Used

- `GET /api/directories/{name}/files`
- `GET /api/sources/{source_id}/files`
- `GET /api/files/{file_id}`
