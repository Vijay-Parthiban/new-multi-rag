"""Pathway-based Airbyte connector worker.

Syncs external data sources (Google Drive, S3, Postgres, etc.) into
per-source MinIO buckets and triggers RAG indexing for linked pipelines.
"""