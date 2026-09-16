# Document Upload

## Status in Current Implementation

No standalone top-level route (`/upload`) exists in the React Router config. Upload functionality is embedded within the Sources and pipeline management interfaces.

## Backend Upload APIs (fully implemented)

Chunked multipart upload is supported end-to-end via:

- `POST /api/uploads/init` - Initialise a new upload session, returns `upload_id`
- `PUT /api/uploads/{upload_id}/chunks/{chunk_index}` - Upload individual chunk
- `POST /api/uploads/{upload_id}/complete` - Finalise and assemble chunks in MinIO

Completed uploads land in the source-specific MinIO bucket and trigger the standard ingestion pipeline: NiFi connector sync -> universal fanout -> all 5 sinks.

## Manual Upload via MinIO Console

Files can also be dropped directly into a source bucket via the MinIO Console at `http://localhost:9001`. The live MinIO monitor (`watch_minio_bucket`) detects new objects and triggers `enqueue_sync_run()` automatically.
