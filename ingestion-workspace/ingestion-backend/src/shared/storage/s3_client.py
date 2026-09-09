import asyncio
import logging
from typing import Any, AsyncGenerator
import aioboto3
from botocore.exceptions import ClientError
from src.shared.config.settings import get_settings

logger = logging.getLogger(__name__)

def _get_endpoint_url() -> str:
    settings = get_settings()
    ep = settings.minio_endpoint
    if not ep.startswith("http://") and not ep.startswith("https://"):
        scheme = "https://" if str(settings.minio_use_ssl).lower() == "true" else "http://"
        return f"{scheme}{ep}"
    return ep

def get_minio_client():
    settings = get_settings()
    session = aioboto3.Session()
    return session.client(
        "s3",
        endpoint_url=_get_endpoint_url(),
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        use_ssl=str(settings.minio_use_ssl).lower() == "true",
    )

class S3Object:
    def __init__(self, key: str, size: int = 0, last_modified: Any = None, etag: str | None = None):
        self.key = key
        self.size = size
        self.last_modified = last_modified
        self.etag = etag
class MinIOEvent:
    def __init__(self, action: str, bucket_key: str):
        self.action = action
        self.bucket_key = bucket_key

def _sync_ensure_bucket(bucket: str) -> None:
    endpoint_url = _get_endpoint_url()
    settings = get_settings()
    try:
        import boto3
        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            use_ssl=str(settings.minio_use_ssl).lower() == "true",
        )
        try:
            s3.head_bucket(Bucket=bucket)
        except Exception:
            s3.create_bucket(Bucket=bucket)
            logger.info("Created bucket %s", bucket)
    except Exception as e:
        logger.warning("Failed ensuring bucket %s: %s", bucket, e)

async def ensure_bucket(bucket: str) -> None:
    await asyncio.to_thread(_sync_ensure_bucket, bucket)

def _sync_delete_object(bucket: str, key: str) -> None:
    endpoint_url = _get_endpoint_url()
    settings = get_settings()
    try:
        import boto3
        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            use_ssl=str(settings.minio_use_ssl).lower() == "true",
        )
        s3.delete_object(Bucket=bucket, Key=key)
        logger.info("Deleted object %s from bucket %s", key, bucket)
    except Exception as e:
        logger.warning("Failed deleting object %s from bucket %s: %s", key, bucket, e)
async def put_object(
    bucket: str = "",
    key: str = "",
    data: bytes | str = b"",
    bucket_name: str = "",
    metadata: dict[str, str] | None = None,
    **kwargs: Any,
) -> None:
    target_bucket = bucket_name or bucket
    if isinstance(data, str):
        data = data.encode("utf-8")
    put_args: dict[str, Any] = {
        "Bucket": target_bucket,
        "Key": key,
        "Body": data,
    }
    if metadata:
        put_args["Metadata"] = {str(k): str(v) for k, v in metadata.items()}
    async with get_minio_client() as s3:
        await s3.put_object(**put_args)

async def get_object(bucket: str, key: str) -> bytes:
    async with get_minio_client() as s3:
        res = await s3.get_object(Bucket=bucket, Key=key)
        async with res["Body"] as stream:
            return await stream.read()

async def delete_object(bucket: str, key: str) -> None:
    await asyncio.to_thread(_sync_delete_object, bucket, key)

def _sync_delete_bucket(bucket: str) -> None:
    endpoint_url = _get_endpoint_url()
    settings = get_settings()
    try:
        import boto3
        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            use_ssl=str(settings.minio_use_ssl).lower() == "true",
        )
        try:
            paginator = s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bucket):
                if "Contents" in page:
                    for obj in page["Contents"]:
                        try:
                            s3.delete_object(Bucket=bucket, Key=obj["Key"])
                        except Exception as e:
                            logger.warning("Error deleting key %s in bucket %s: %s", obj.get("Key"), bucket, e)
            s3.delete_bucket(Bucket=bucket)
            logger.info("Successfully deleted MinIO bucket %s", bucket)
        except Exception as e:
            logger.warning("Could not delete bucket %s: %s", bucket, e)
    except Exception as e:
        logger.warning("Failed deleting bucket %s: %s", bucket, e)

async def delete_bucket(bucket: str) -> None:
    await asyncio.to_thread(_sync_delete_bucket, bucket)
async def head_object(bucket: str, key: str) -> dict[str, Any]:
    async with get_minio_client() as s3:
        res = await s3.head_object(Bucket=bucket, Key=key)
        return {
            "size": res.get("ContentLength", 0),
            "last_modified": res.get("LastModified"),
            "content_type": res.get("ContentType"),
        }

async def list_objects(bucket: str, prefix: str = "") -> list[S3Object]:
    objects = []
    async with get_minio_client() as s3:
        try:
            paginator = s3.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                for item in page.get("Contents", []):
                    objects.append(
                        S3Object(
                            key=item["Key"],
                            size=item.get("Size", 0),
                            last_modified=item.get("LastModified"),
                            etag=item.get("ETag"),
                        )
                    )
        except ClientError as e:
            logger.warning("Error listing objects in bucket %s: %s", bucket, e)
    return objects

async def setup_bucket_notification(bucket: str, webhook_url: str) -> None:
    logger.info("Setting up bucket notification for %s -> %s", bucket, webhook_url)

async def watch_minio_bucket(bucket: str, poll_interval: int = 5) -> AsyncGenerator[MinIOEvent, None]:
    seen: set[str] = set()
    while True:
        try:
            objs = await list_objects(bucket)
            for o in objs:
                if o.key not in seen:
                    seen.add(o.key)
                    yield MinIOEvent(action="upload", bucket_key=o.key)
        except Exception as e:
            logger.debug("watch_minio_bucket poll error: %s", e)
        await asyncio.sleep(poll_interval)
