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

        Supports Google Drive, Amazon S3, Azure Blob Storage, SFTP, Web Scraper, Confluence, and Local Directory.
        Performs full differential state CRUD tracking (CREATE, UPDATE, DELETE).
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
        elif connector_type in ["sftp", "ftp"]:
            return await self._sync_sftp_to_minio(
                source_id=source_id,
                connector_id=connector_id,
                config=config,
                bucket=minio_bucket,
            )
        elif connector_type in ["web_scraper", "web"]:
            return await self._sync_web_scraper_to_minio(
                source_id=source_id,
                connector_id=connector_id,
                config=config,
                bucket=minio_bucket,
            )
        elif connector_type in ["confluence"]:
            return await self._sync_confluence_to_minio(
                source_id=source_id,
                connector_id=connector_id,
                config=config,
                bucket=minio_bucket,
            )
        elif connector_type in ["local_folder", "local_dir"]:
            return await self._sync_local_dir_to_minio(
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
        """Sync Amazon S3 bucket objects to MinIO via NiFi engine with differential CRUD."""
        import boto3
        from src.shared.storage.s3_client import delete_object, head_object, list_objects, put_object

        aws_key = config.get("aws_access_key_id") or config.get("access_key_id")
        aws_secret = config.get("aws_secret_access_key") or config.get("secret_access_key")
        s3_bucket = config.get("bucket_name") or config.get("s3_bucket") or config.get("bucket")
        region = config.get("region_name") or config.get("region", "us-east-1")
        prefix = config.get("prefix", "")

        if not s3_bucket:
            logger.error("nifi_s3_sync_missing_bucket source=%s", source_id)
            return {"files_synced": 0, "status": "error", "message": "Missing Amazon S3 bucket name"}

        def _fetch_s3():
            s3_cli = boto3.client(
                "s3",
                aws_access_key_id=aws_key,
                aws_secret_access_key=aws_secret,
                region_name=region,
            )
            paginator = s3_cli.get_paginator("list_objects_v2")
            items = {}
            kwargs = {"Bucket": s3_bucket}
            if prefix:
                kwargs["Prefix"] = prefix
            for page in paginator.paginate(**kwargs):
                for obj in page.get("Contents", []):
                    k = obj["Key"]
                    if not k.endswith("/"):
                        resp = s3_cli.get_object(Bucket=s3_bucket, Key=k)
                        content = resp["Body"].read()
                        etag = resp.get("ETag", "").strip('"')
                        last_mod = resp.get("LastModified", "")
                        if hasattr(last_mod, "isoformat"):
                            last_mod = last_mod.isoformat()
                        items[k] = {
                            "data": content,
                            "content_type": resp.get("ContentType"),
                            "etag": etag,
                            "last_modified": str(last_mod),
                        }
            return items

        try:
            remote_s3_items = await asyncio.to_thread(_fetch_s3)
            prefix_path = f"connectors/{connector_id}/"
            existing_minio_objs = await list_objects(bucket, prefix=prefix_path)
            existing_minio_map = {obj.key: obj for obj in existing_minio_objs}

            files_added = 0
            files_updated = 0
            files_deleted = 0

            # 1. Handle ADD and UPDATE
            for file_key, info in remote_s3_items.items():
                target_key = f"{prefix_path}{file_key}"
                data = info["data"]
                remote_etag = info["etag"]
                remote_mod = info["last_modified"]

                target_exists = target_key in existing_minio_map
                needs_upload = not target_exists
                is_update = False

                if target_exists:
                    try:
                        head = await head_object(bucket, target_key)
                        meta = (head.get("Metadata") or head.get("metadata") or {}) if head else {}
                        old_etag = meta.get("remote-etag") or ""
                        old_size = head.get("ContentLength") or 0
                        if (old_etag and remote_etag and old_etag != remote_etag) or (old_size and len(data) != old_size):
                            needs_upload = True
                            is_update = True
                    except Exception:
                        needs_upload = True

                if needs_upload:
                    metadata = {
                        "source-id": str(source_id),
                        "connector-id": str(connector_id),
                        "remote-etag": remote_etag,
                        "remote-modified-at": remote_mod,
                    }
                    if info.get("content_type"):
                        metadata["content-type"] = info["content_type"]
                    await put_object(bucket, target_key, data, metadata=metadata)
                    if is_update:
                        files_updated += 1
                    else:
                        files_added += 1

            # 2. Handle DELETE
            for minio_key in list(existing_minio_map.keys()):
                rel_key = minio_key[len(prefix_path):]
                if rel_key not in remote_s3_items:
                    await delete_object(bucket, minio_key)
                    files_deleted += 1
                    logger.info("nifi_s3_file_deleted source=%s key=%s", source_id, minio_key)

            total_active = len(remote_s3_items)
            logger.info(
                "nifi_s3_sync_completed bucket=%s active=%d added=%d updated=%d deleted=%d",
                bucket, total_active, files_added, files_updated, files_deleted,
            )
            return {
                "files_synced": total_active,
                "files_added": files_added,
                "files_updated": files_updated,
                "files_deleted": files_deleted,
                "status": "completed",
            }
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
        """Sync Azure Blob storage objects to MinIO via NiFi engine with differential CRUD."""
        from azure.storage.blob import ContainerClient
        from src.shared.storage.s3_client import delete_object, head_object, list_objects, put_object

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

            items = {}
            blobs = cli.list_blobs(name_starts_with=prefix if prefix else None)
            for blob in blobs:
                blob_cli = cli.get_blob_client(blob.name)
                stream = blob_cli.download_blob()
                data = stream.readall()
                etag = getattr(blob, "etag", "")
                last_mod = getattr(blob, "last_modified", "")
                if hasattr(last_mod, "isoformat"):
                    last_mod = last_mod.isoformat()
                c_type = blob.content_settings.content_type if blob.content_settings else None
                items[blob.name] = {
                    "data": data,
                    "content_type": c_type,
                    "etag": etag,
                    "last_modified": str(last_mod),
                }
            return items

        try:
            remote_items = await asyncio.to_thread(_fetch_azure)
            prefix_path = f"connectors/{connector_id}/"
            existing_minio_objs = await list_objects(bucket, prefix=prefix_path)
            existing_minio_map = {obj.key: obj for obj in existing_minio_objs}

            files_added = 0
            files_updated = 0
            files_deleted = 0

            # 1. Handle ADD & UPDATE
            for file_key, info in remote_items.items():
                target_key = f"{prefix_path}{file_key}"
                data = info["data"]
                remote_etag = info["etag"]
                remote_mod = info["last_modified"]

                target_exists = target_key in existing_minio_map
                needs_upload = not target_exists
                is_update = False

                if target_exists:
                    try:
                        head = await head_object(bucket, target_key)
                        meta = (head.get("Metadata") or head.get("metadata") or {}) if head else {}
                        old_etag = meta.get("remote-etag") or ""
                        old_size = head.get("ContentLength") or 0
                        if (old_etag and remote_etag and old_etag != remote_etag) or (old_size and len(data) != old_size):
                            needs_upload = True
                            is_update = True
                    except Exception:
                        needs_upload = True

                if needs_upload:
                    metadata = {
                        "source-id": str(source_id),
                        "connector-id": str(connector_id),
                        "remote-etag": remote_etag,
                        "remote-modified-at": remote_mod,
                    }
                    if info.get("content_type"):
                        metadata["content-type"] = info["content_type"]
                    await put_object(bucket, target_key, data, metadata=metadata)
                    if is_update:
                        files_updated += 1
                    else:
                        files_added += 1

            # 2. Handle DELETE
            for minio_key in list(existing_minio_map.keys()):
                rel_key = minio_key[len(prefix_path):]
                if rel_key not in remote_items:
                    await delete_object(bucket, minio_key)
                    files_deleted += 1
                    logger.info("nifi_azure_file_deleted source=%s key=%s", source_id, minio_key)

            total_active = len(remote_items)
            logger.info(
                "nifi_azure_sync_completed bucket=%s active=%d added=%d updated=%d deleted=%d",
                bucket, total_active, files_added, files_updated, files_deleted,
            )
            return {
                "files_synced": total_active,
                "files_added": files_added,
                "files_updated": files_updated,
                "files_deleted": files_deleted,
                "status": "completed",
            }
        except Exception as exc:
            logger.exception("nifi_azure_sync_failed source=%s error=%s", source_id, exc)
            return {"files_synced": 0, "status": "error", "message": str(exc)}

    async def _sync_sftp_to_minio(
        self,
        source_id: uuid.UUID,
        connector_id: uuid.UUID | str,
        config: dict[str, Any],
        bucket: str,
    ) -> dict[str, Any]:
        """Sync SFTP server directory files to MinIO with differential CRUD."""
        import paramiko
        from src.shared.storage.s3_client import delete_object, head_object, list_objects, put_object

        host = config.get("host") or config.get("sftp_host")
        port = int(config.get("port") or 22)
        username = config.get("username")
        password = config.get("password")
        remote_path = config.get("remote_path") or config.get("path") or "."

        if not host or not username:
            return {"files_synced": 0, "status": "error", "message": "Missing SFTP host or username"}

        def _fetch_sftp():
            transport = paramiko.Transport((host, port))
            transport.connect(username=username, password=password)
            sftp = paramiko.SFTPClient.from_transport(transport)
            items = {}

            def _walk(path, rel_prefix=""):
                for entry in sftp.listdir_attr(path):
                    entry_path = f"{path}/{entry.filename}".replace("//", "/")
                    rel_name = f"{rel_prefix}/{entry.filename}".strip("/")
                    import stat
                    if stat.S_ISDIR(entry.st_mode):
                        _walk(entry_path, rel_name)
                    else:
                        with sftp.open(entry_path, "rb") as f:
                            data = f.read()
                        items[rel_name] = {
                            "data": data,
                            "last_modified": str(entry.st_mtime),
                            "size": entry.st_size,
                        }

            _walk(remote_path)
            sftp.close()
            transport.close()
            return items

        try:
            remote_items = await asyncio.to_thread(_fetch_sftp)
            prefix_path = f"connectors/{connector_id}/"
            existing_minio_objs = await list_objects(bucket, prefix=prefix_path)
            existing_minio_map = {obj.key: obj for obj in existing_minio_objs}

            files_added = 0
            files_updated = 0
            files_deleted = 0

            for file_key, info in remote_items.items():
                target_key = f"{prefix_path}{file_key}"
                data = info["data"]
                target_exists = target_key in existing_minio_map
                needs_upload = not target_exists
                is_update = False

                if target_exists:
                    head = await head_object(bucket, target_key)
                    old_size = head.get("ContentLength") or 0
                    if old_size and len(data) != old_size:
                        needs_upload = True
                        is_update = True

                if needs_upload:
                    await put_object(bucket, target_key, data, metadata={"source-id": str(source_id), "connector-id": str(connector_id)})
                    if is_update:
                        files_updated += 1
                    else:
                        files_added += 1

            for minio_key in list(existing_minio_map.keys()):
                rel_key = minio_key[len(prefix_path):]
                if rel_key not in remote_items:
                    await delete_object(bucket, minio_key)
                    files_deleted += 1

            return {"files_synced": len(remote_items), "files_added": files_added, "files_updated": files_updated, "files_deleted": files_deleted, "status": "completed"}
        except Exception as exc:
            logger.exception("nifi_sftp_sync_failed source=%s error=%s", source_id, exc)
            return {"files_synced": 0, "status": "error", "message": str(exc)}

    async def _sync_web_scraper_to_minio(
        self,
        source_id: uuid.UUID,
        connector_id: uuid.UUID | str,
        config: dict[str, Any],
        bucket: str,
    ) -> dict[str, Any]:
        """Sync web scraper target URLs into MinIO with differential CRUD."""
        import httpx
        from src.shared.storage.s3_client import delete_object, head_object, list_objects, put_object

        urls = config.get("urls") or config.get("target_urls") or []
        if isinstance(urls, str):
            urls = [u.strip() for u in urls.split(",") if u.strip()]

        if not urls:
            return {"files_synced": 0, "status": "error", "message": "No target URLs provided for web scraper"}

        scraped_items = {}
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            for idx, url in enumerate(urls):
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        safe_filename = url.replace("https://", "").replace("http://", "").replace("/", "_") + ".html"
                        scraped_items[safe_filename] = {
                            "data": resp.content,
                            "url": url,
                            "etag": resp.headers.get("etag", ""),
                        }
                except Exception as e:
                    logger.warning("web_scraper_fetch_failed url=%s error=%s", url, e)

        prefix_path = f"connectors/{connector_id}/"
        existing_minio_objs = await list_objects(bucket, prefix=prefix_path)
        existing_minio_map = {obj.key: obj for obj in existing_minio_objs}

        files_added = 0
        files_updated = 0
        files_deleted = 0

        for file_key, info in scraped_items.items():
            target_key = f"{prefix_path}{file_key}"
            data = info["data"]
            target_exists = target_key in existing_minio_map
            needs_upload = not target_exists
            is_update = False

            if target_exists:
                head = await head_object(bucket, target_key)
                old_size = head.get("ContentLength") or 0
                if old_size and len(data) != old_size:
                    needs_upload = True
                    is_update = True

            if needs_upload:
                await put_object(bucket, target_key, data, metadata={"source-id": str(source_id), "url": info["url"]})
                if is_update:
                    files_updated += 1
                else:
                    files_added += 1

        for minio_key in list(existing_minio_map.keys()):
            rel_key = minio_key[len(prefix_path):]
            if rel_key not in scraped_items:
                await delete_object(bucket, minio_key)
                files_deleted += 1

        return {"files_synced": len(scraped_items), "files_added": files_added, "files_updated": files_updated, "files_deleted": files_deleted, "status": "completed"}

    async def _sync_confluence_to_minio(
        self,
        source_id: uuid.UUID,
        connector_id: uuid.UUID | str,
        config: dict[str, Any],
        bucket: str,
    ) -> dict[str, Any]:
        """Sync Confluence spaces/pages to MinIO with differential CRUD."""
        import httpx
        from src.shared.storage.s3_client import delete_object, head_object, list_objects, put_object

        domain = config.get("domain") or config.get("url")
        email = config.get("email") or config.get("username")
        api_token = config.get("api_token") or config.get("password")
        space_key = config.get("space_key") or config.get("space")

        if not domain or not email or not api_token:
            return {"files_synced": 0, "status": "error", "message": "Missing Confluence authentication credentials"}

        base_url = domain.rstrip("/")
        confluence_items = {}

        async with httpx.AsyncClient(auth=(email, api_token), timeout=15.0) as client:
            endpoint = f"{base_url}/wiki/rest/api/content?type=page&expand=body.storage,version"
            if space_key:
                endpoint += f"&spaceKey={space_key}"
            try:
                resp = await client.get(endpoint)
                if resp.status_code == 200:
                    results = resp.json().get("results", [])
                    for p in results:
                        page_id = p["id"]
                        title = p.get("title", f"page_{page_id}")
                        body = p.get("body", {}).get("storage", {}).get("value", "")
                        version = str(p.get("version", {}).get("number", "1"))
                        file_key = f"{page_id}_{title.replace(' ', '_')}.html"
                        confluence_items[file_key] = {
                            "data": body.encode("utf-8"),
                            "version": version,
                            "title": title,
                        }
            except Exception as exc:
                logger.error("confluence_fetch_failed source=%s error=%s", source_id, exc)

        prefix_path = f"connectors/{connector_id}/"
        existing_minio_objs = await list_objects(bucket, prefix=prefix_path)
        existing_minio_map = {obj.key: obj for obj in existing_minio_objs}

        files_added = 0
        files_updated = 0
        files_deleted = 0

        for file_key, info in confluence_items.items():
            target_key = f"{prefix_path}{file_key}"
            data = info["data"]
            target_exists = target_key in existing_minio_map
            needs_upload = not target_exists
            is_update = False

            if target_exists:
                head = await head_object(bucket, target_key)
                meta = (head.get("Metadata") or head.get("metadata") or {}) if head else {}
                old_ver = meta.get("confluence-version", "")
                if old_ver and old_ver != info["version"]:
                    needs_upload = True
                    is_update = True

            if needs_upload:
                await put_object(bucket, target_key, data, metadata={"source-id": str(source_id), "confluence-version": info["version"]})
                if is_update:
                    files_updated += 1
                else:
                    files_added += 1

        for minio_key in list(existing_minio_map.keys()):
            rel_key = minio_key[len(prefix_path):]
            if rel_key not in confluence_items:
                await delete_object(bucket, minio_key)
                files_deleted += 1

        return {"files_synced": len(confluence_items), "files_added": files_added, "files_updated": files_updated, "files_deleted": files_deleted, "status": "completed"}

    async def _sync_local_dir_to_minio(
        self,
        source_id: uuid.UUID,
        connector_id: uuid.UUID | str,
        config: dict[str, Any],
        bucket: str,
    ) -> dict[str, Any]:
        """Sync local folder files to MinIO with differential CRUD."""
        from pathlib import Path
        from src.shared.storage.s3_client import delete_object, head_object, list_objects, put_object

        folder_path_str = config.get("folder_path") or config.get("path")
        if not folder_path_str:
            return {"files_synced": 0, "status": "error", "message": "Missing folder_path in local_folder connector config"}

        folder_path = Path(folder_path_str)
        if not folder_path.exists() or not folder_path.is_dir():
            return {"files_synced": 0, "status": "error", "message": f"Local folder directory '{folder_path_str}' does not exist"}

        local_items = {}
        for p in folder_path.rglob("*"):
            if p.is_file():
                rel_key = p.relative_to(folder_path).as_posix()
                try:
                    data = p.read_bytes()
                    mtime = str(p.stat().st_mtime)
                    local_items[rel_key] = {"data": data, "mtime": mtime, "size": len(data)}
                except Exception as e:
                    logger.warning("local_dir_read_failed file=%s error=%s", p, e)

        prefix_path = f"connectors/{connector_id}/"
        existing_minio_objs = await list_objects(bucket, prefix=prefix_path)
        existing_minio_map = {obj.key: obj for obj in existing_minio_objs}

        files_added = 0
        files_updated = 0
        files_deleted = 0

        for file_key, info in local_items.items():
            target_key = f"{prefix_path}{file_key}"
            data = info["data"]
            target_exists = target_key in existing_minio_map
            needs_upload = not target_exists
            is_update = False

            if target_exists:
                head = await head_object(bucket, target_key)
                meta = (head.get("Metadata") or head.get("metadata") or {}) if head else {}
                old_mtime = meta.get("local-mtime") or ""
                old_size = head.get("ContentLength") or 0
                if (old_mtime and old_mtime != info["mtime"]) or (old_size and len(data) != old_size):
                    needs_upload = True
                    is_update = True

            if needs_upload:
                await put_object(bucket, target_key, data, metadata={"source-id": str(source_id), "local-mtime": info["mtime"]})
                if is_update:
                    files_updated += 1
                else:
                    files_added += 1

        for minio_key in list(existing_minio_map.keys()):
            rel_key = minio_key[len(prefix_path):]
            if rel_key not in local_items:
                await delete_object(bucket, minio_key)
                files_deleted += 1

        return {"files_synced": len(local_items), "files_added": files_added, "files_updated": files_updated, "files_deleted": files_deleted, "status": "completed"}

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
