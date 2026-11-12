"""Store an uploaded golden dataset in MinIO.

A dataset is never written into a Knowledge Product's document bucket. The ingestion
service indexes every object it finds in that bucket, so a dataset there becomes corpus and
is chunked into that product's destinations. Every dataset goes into `dataset_fabric_bucket`
instead, which no source points at. The dataset row records the bucket and key it used.

ponytail: the MinIO SDK is synchronous, so each call goes through `asyncio.to_thread`.
An upload is a few megabytes and the request waits for it; a queue would add a status the
page has to poll. Add one if a dataset grows past a few tens of megabytes.
"""

from __future__ import annotations

import asyncio
import io
import logging
from pathlib import Path

from minio import Minio
from minio.error import S3Error
from rag_shared.config import Settings

logger = logging.getLogger(__name__)

CONTENT_TYPES = {
    ".csv": "text/csv",
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".parquet": "application/vnd.apache.parquet",
}


class DatasetStorageError(RuntimeError):
    """MinIO or the ingestion service refused the read or the write."""


def content_type_for(filename: str) -> str:
    return CONTENT_TYPES.get(Path(filename).suffix.lower(), "application/octet-stream")


def object_key(profile_id: str, kind: str, filename: str) -> str:
    """`datasets/<profile>/<kind>/<file>`.

    The kind is in the key so a single-turn and a multi-turn upload of the same file name
    cannot overwrite each other.
    """
    name = Path(filename or "dataset").name
    return f"datasets/{profile_id}/{kind}/{name}"


def versioned_key(
    knowledge_product_id: str, profile_id: str, version_no: int, kind: str, filename: str
) -> str:
    """`datasets/<kp>/<profile>/v<version>/<kind>/<file>`.

    One Knowledge Product, one profile, one version, one kind, one file. Two versions of
    one profile therefore never share an object, and a product's whole tree is one prefix.
    The bucket is `dataset-fabric`, which no ingestion source lists, so these files never
    reach a Knowledge Product's destinations.
    """
    name = Path(filename or "dataset").name
    return f"datasets/{knowledge_product_id}/{profile_id}/v{version_no}/{kind}/{name}"


def _client(settings: Settings) -> Minio:
    raw = (settings.minio_endpoint or "").strip()
    secure = bool(settings.minio_use_ssl) or raw.startswith("https://")
    host = raw.replace("https://", "").replace("http://", "").rstrip("/")
    if not host:
        raise DatasetStorageError("MINIO_ENDPOINT is empty.")
    # A fresh client per call: construction opens no socket, and a cached one would keep
    # the first settings object alive across a test that swaps the configuration.
    return Minio(
        host,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=secure,
    )


def resolve_bucket(settings: Settings) -> str:
    """The bucket that holds every dataset file.

    One bucket, never a Knowledge Product's. The ingestion service lists a Knowledge
    Product bucket whole, so a dataset placed there is read as a document, chunked and
    embedded into that product's destinations. No source points at this bucket.
    """
    return settings.dataset_fabric_bucket


def _sync_put(settings: Settings, bucket: str, key: str, data: bytes, content_type: str) -> None:
    client = _client(settings)
    try:
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
        client.put_object(
            bucket, key, io.BytesIO(data), length=len(data), content_type=content_type
        )
    except S3Error as exc:
        raise DatasetStorageError(f"MinIO refused the write to {bucket}/{key}: {exc}") from exc


def _sync_get(settings: Settings, bucket: str, key: str) -> bytes:
    client = _client(settings)
    try:
        response = client.get_object(bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()
    except S3Error as exc:
        raise DatasetStorageError(f"MinIO refused the read of {bucket}/{key}: {exc}") from exc


def _sync_delete(settings: Settings, bucket: str, key: str) -> None:
    client = _client(settings)
    try:
        client.remove_object(bucket, key)
    except S3Error as exc:
        raise DatasetStorageError(f"MinIO refused the delete of {bucket}/{key}: {exc}") from exc


async def put_dataset(
    settings: Settings, *, bucket: str, key: str, data: bytes, filename: str
) -> str:
    await asyncio.to_thread(_sync_put, settings, bucket, key, data, content_type_for(filename))
    return f"s3://{bucket}/{key}"


async def get_dataset(settings: Settings, *, bucket: str, key: str) -> bytes:
    return await asyncio.to_thread(_sync_get, settings, bucket, key)


async def delete_dataset(settings: Settings, *, bucket: str, key: str) -> None:
    """Remove a stored file. A missing object is not an error: the row is going away too."""
    try:
        await asyncio.to_thread(_sync_delete, settings, bucket, key)
    except DatasetStorageError as exc:
        logger.warning("dataset object delete failed bucket=%s key=%s error=%s", bucket, key, exc)
