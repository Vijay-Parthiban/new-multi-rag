"""Store an uploaded golden dataset in MinIO.

A dataset profile that names a pipeline writes into that Knowledge Product's document
bucket, so the dataset sits beside the corpus it grades. A profile with no pipeline writes
into one shared bucket. The route resolves the bucket and this module does the I/O, which
keeps the ingestion service the only place that knows how a Knowledge Product maps to a
bucket.

ponytail: the MinIO SDK is synchronous, so each call goes through `asyncio.to_thread`.
An upload is a few megabytes and the request waits for it; a queue would add a status the
page has to poll. Add one if a dataset grows past a few tens of megabytes.
"""

from __future__ import annotations

import asyncio
import io
import logging
from pathlib import Path

import httpx
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


async def resolve_bucket(settings: Settings, knowledge_product_id: str | None) -> str:
    """The bucket that holds this profile's files.

    A linked profile uses the first document bucket of its Knowledge Product. A product
    with no source yet, or a product the ingestion service no longer has, falls back to the
    shared bucket; the dataset row records which one was used, so the page never guesses.
    """
    if not knowledge_product_id:
        return settings.dataset_fabric_bucket

    base = settings.ingestion_service_url.rstrip("/")
    headers = {"X-API-Key": settings.api_key} if settings.api_key else {}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{base}/api/knowledge-products/{knowledge_product_id}", headers=headers
            )
    except httpx.RequestError as exc:
        raise DatasetStorageError(
            f"Cannot reach the ingestion service to resolve the bucket: {exc}"
        ) from exc

    if response.status_code == 404:
        logger.warning("knowledge product gone, using the shared bucket kp=%s", knowledge_product_id)
        return settings.dataset_fabric_bucket
    if response.status_code != 200:
        raise DatasetStorageError(
            "The ingestion service refused the Knowledge Product read: "
            f"{response.status_code} {response.text[:200]}"
        )

    sources = response.json().get("sources") or []
    buckets = sorted(
        {
            str(source["minio_bucket"])
            for source in sources
            if source.get("minio_bucket") and not str(source["minio_bucket"]).startswith("local-")
        }
    )
    if not buckets:
        logger.info("knowledge product has no document bucket kp=%s", knowledge_product_id)
        return settings.dataset_fabric_bucket
    return buckets[0]


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
