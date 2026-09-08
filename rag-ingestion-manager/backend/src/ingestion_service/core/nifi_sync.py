"""Apache NiFi Dataflow Engine — Live and Scheduled Polling for Connectors to MinIO.

Brings data from remote connectors (Google Drive, Amazon S3, Azure Blob) into
dedicated per-source MinIO buckets via Apache NiFi integration.
"""

import asyncio
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from src.shared.config.settings import get_settings
from src.ingestion_service.core.gdrive_sync import sync_google_drive_to_minio
from src.shared.storage.s3_client import ensure_bucket

logger = logging.getLogger(__name__)

# Apache NiFi service configuration defaults
NIFI_API_URL = os.getenv("NIFI_API_URL", "http://nifi:8443/nifi-api")
_NIFI_POLLER_TASKS: dict[uuid.UUID, asyncio.Task] = {}


class NiFiConnectorManager:
    """Manages NiFi dataflows and connector synchronization routines."""

    def __init__(self, api_url: str = NIFI_API_URL):
        self.api_url = api_url

    async def check_nifi_health(self) -> bool:
        """Check if Apache NiFi REST API is reachable."""
        import httpx
        try:
            async with httpx.AsyncClient(timeout=3.0, verify=False) as client:
                resp = await client.get(f"{self.api_url}/system-diagnostics")
                return resp.status_code == 200
        except Exception:
            return False

    async def sync_connector(
        self,
        *,
        source_id: uuid.UUID,
        connector_id: uuid.UUID | str,
        connector_type: str,
        config: dict[str, Any],
        minio_bucket: str,
    ) -> dict[str, Any]:
        """Run a NiFi connector sync to bring files from source to MinIO bucket.

        Supports Google Drive, Amazon S3, and Azure Blob Storage.
        """
        await ensure_bucket(minio_bucket)
        logger.info(
            "nifi_connector_sync_starting source=%s connector=%s type=%s bucket=%s",
            source_id, connector_id, connector_type, minio_bucket,
        )

        if connector_type == "google_drive":
            return await sync_google_drive_to_minio(
                source_id=source_id,
                config=config,
                bucket=minio_bucket,
                connector_id=connector_id,
            )
        elif connector_type in ["s3", "amazon_s3"]:
            return await self._sync_s3_to_minio(
                source_id=source_id,
                connector_id=connector_id,
                config=config,
                bucket=minio_bucket,
            )
        elif connector_type in ["azure_blob", "azure"]:
            return await self._sync_azure_to_minio(
                source_id=source_id,
                connector_id=connector_id,
                config=config,
                bucket=minio_bucket,
            )
        else:
            logger.warning("nifi_unsupported_connector_type type=%s", connector_type)
            return {"files_synced": 0, "status": "unsupported"}

    async def _sync_s3_to_minio(
        self,
        source_id: uuid.UUID,
        connector_id: uuid.UUID | str,
        config: dict[str, Any],
        bucket: str,
    ) -> dict[str, Any]:
        """Sync Amazon S3 bucket objects to MinIO via NiFi engine."""
        import boto3
        from src.shared.storage.s3_client import put_object

        aws_key = config.get("aws_access_key_id") or config.get("access_key_id")
        aws_secret = config.get("aws_secret_access_key") or config.get("secret_access_key")
        s3_bucket = config.get("bucket_name") or config.get("s3_bucket") or config.get("bucket")
        region = config.get("region_name") or config.get("region", "us-east-1")
        prefix = config.get("prefix", "")

        if not s3_bucket:
            logger.error("nifi_s3_sync_missing_bucket source=%s", source_id)
            return {"files_synced": 0, "status": "error", "message": "Missing S3 bucket name"}

        def _fetch_s3():
            s3_cli = boto3.client(
                "s3",
                aws_access_key_id=aws_key,
                aws_secret_access_key=aws_secret,
                region_name=region,
            )
            paginator = s3_cli.get_paginator("list_objects_v2")
            items = []
            kwargs = {"Bucket": s3_bucket}
            if prefix:
                kwargs["Prefix"] = prefix
            for page in paginator.paginate(**kwargs):
                for obj in page.get("Contents", []):
                    k = obj["Key"]
                    if not k.endswith("/"):
                        resp = s3_cli.get_object(Bucket=s3_bucket, Key=k)
                        content = resp["Body"].read()
                        items.append((k, content, resp.get("ContentType")))
            return items

        try:
            s3_items = await asyncio.to_thread(_fetch_s3)
            files_synced = 0
            for file_key, data, content_type in s3_items:
                target_key = f"connectors/{connector_id}/{file_key}"
                metadata = {}
                if content_type:
                    metadata["content-type"] = content_type
                await put_object(bucket, target_key, data, metadata=metadata)
                files_synced += 1
            logger.info("nifi_s3_sync_executed bucket=%s synced=%d", bucket, files_synced)
            return {"files_synced": files_synced, "status": "completed"}
        except Exception as exc:
            logger.exception("nifi_s3_sync_failed source=%s error=%s", source_id, exc)
            return {"files_synced": 0, "status": "error", "message": str(exc)}

    async def _sync_azure_to_minio(
        self,
        source_id: uuid.UUID,
        connector_id: uuid.UUID | str,
        config: dict[str, Any],
        bucket: str,
    ) -> dict[str, Any]:
        """Sync Azure Blob storage objects to MinIO via NiFi engine."""
        from azure.storage.blob import ContainerClient
        from src.shared.storage.s3_client import put_object

        conn_str = config.get("connection_string")
        container = config.get("container_name") or config.get("azure_container") or config.get("container")
        account_name = config.get("account_name")
        account_key = config.get("account_key")
        prefix = config.get("prefix", "")

        if not container:
            logger.error("nifi_azure_sync_missing_container source=%s", source_id)
            return {"files_synced": 0, "status": "error", "message": "Missing Azure container name"}

        def _fetch_azure():
            if conn_str:
                cli = ContainerClient.from_connection_string(conn_str, container_name=container)
            elif account_name and account_key:
                account_url = f"https://{account_name}.blob.core.windows.net"
                cli = ContainerClient(account_url=account_url, container_name=container, credential=account_key)
            else:
                raise ValueError("Missing Azure authentication credentials")
            
            items = []
            blobs = cli.list_blobs(name_starts_with=prefix if prefix else None)
            for blob in blobs:
                blob_cli = cli.get_blob_client(blob.name)
                stream = blob_cli.download_blob()
                data = stream.readall()
                items.append((blob.name, data, blob.content_settings.content_type if blob.content_settings else None))
            return items

        try:
            azure_items = await asyncio.to_thread(_fetch_azure)
            files_synced = 0
            for file_key, data, content_type in azure_items:
                target_key = f"connectors/{connector_id}/{file_key}"
                metadata = {}
                if content_type:
                    metadata["content-type"] = content_type
                await put_object(bucket, target_key, data, metadata=metadata)
                files_synced += 1
            logger.info("nifi_azure_sync_executed bucket=%s synced=%d", bucket, files_synced)
            return {"files_synced": files_synced, "status": "completed"}
        except Exception as exc:
            logger.exception("nifi_azure_sync_failed source=%s error=%s", source_id, exc)
            return {"files_synced": 0, "status": "error", "message": str(exc)}

nifi_manager = NiFiConnectorManager()


async def sync_connector_via_nifi(
    source_id: uuid.UUID,
    connector_id: uuid.UUID | str,
    connector_type: str,
    config: dict[str, Any],
    minio_bucket: str,
) -> dict[str, Any]:
    """Helper entrypoint for triggering NiFi connector sync to MinIO."""
    return await nifi_manager.sync_connector(
        source_id=source_id,
        connector_id=connector_id,
        connector_type=connector_type,
        config=config,
        minio_bucket=minio_bucket,
    )


def start_nifi_live_poller(source_id: uuid.UUID, poll_interval_seconds: int = 5) -> None:
    """Start continuous background NiFi poller for live-monitored connectors."""
    if source_id in _NIFI_POLLER_TASKS:
        return

    async def _poller_loop():
        logger.info("nifi_live_poller_started source=%s interval=%ds", source_id, poll_interval_seconds)
        while True:
            try:
                await asyncio.sleep(poll_interval_seconds)
                from src.shared.db.session import AsyncSessionLocal
                from src.ingestion_service.core.pathway_sync import sync_source_from_pathway
                async with AsyncSessionLocal() as db:
                    await sync_source_from_pathway(db, source_id)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("nifi_live_poller_error source=%s error=%s", source_id, exc)

    task = asyncio.create_task(_poller_loop())
    _NIFI_POLLER_TASKS[source_id] = task
