"""Google Drive → MinIO sync using service-account credentials.

Downloads files from a shared Google Drive folder and uploads them to the
source's dedicated MinIO bucket. Replaces the broken Pathway/Airbyte
connector path for google_drive connectors.

Flow:
  1. Authenticate via service-account JSON stored in connector config.
  2. List all files in the target Drive folder (recursive).
  3. Download each file and stream it into MinIO under
     ``gdrive-sync/{source_id}/{file_id}/{filename}``.
  4. Return the count of files written so the caller can update status.
"""

import io
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from src.shared.config.settings import get_settings
from src.shared.storage.s3_client import ensure_bucket, put_object

logger = logging.getLogger(__name__)

# Google Drive MIME types that are workspace docs (need export, not download)
_EXPORT_MIME_MAP: dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
    "application/vnd.google-apps.drawing": ("image/png", ".png"),
}

# Workspace types we skip entirely (no meaningful file content)
_SKIP_MIME_TYPES = frozenset({
    "application/vnd.google-apps.folder",
    "application/vnd.google-apps.form",
    "application/vnd.google-apps.map",
    "application/vnd.google-apps.site",
    "application/vnd.google-apps.shortcut",
})


def _extract_folder_id(folder_url_or_id: str) -> str:
    """Extract the folder ID from a Google Drive URL or plain ID."""
    folder_url_or_id = folder_url_or_id.strip()
    # Handle full URLs like https://drive.google.com/drive/u/0/folders/14IXH...
    if "/folders/" in folder_url_or_id:
        # Strip query params (?usp=sharing etc.)
        part = folder_url_or_id.split("/folders/")[-1]
        return part.split("?")[0].split("#")[0].strip()
    return folder_url_or_id


def _build_drive_service(service_account_json: dict[str, Any]):
    """Build authenticated Google Drive API service from service-account key."""
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    scopes = ["https://www.googleapis.com/auth/drive.readonly"]
    creds = Credentials.from_service_account_info(service_account_json, scopes=scopes)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _list_files_in_folder(service, folder_id: str) -> list[dict[str, Any]]:
    """Recursively list all files in a Google Drive folder."""
    all_files: list[dict[str, Any]] = []
    folders_to_scan = [folder_id]

    while folders_to_scan:
        current_folder = folders_to_scan.pop(0)
        page_token = None

        while True:
            response = (
                service.files()
                .list(
                    q=f"'{current_folder}' in parents and trashed = false",
                    fields="nextPageToken, files(id, name, mimeType, size, modifiedTime)",
                    pageSize=100,
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )

            for file_meta in response.get("files", []):
                mime = file_meta.get("mimeType", "")
                if mime == "application/vnd.google-apps.folder":
                    folders_to_scan.append(file_meta["id"])
                elif mime not in _SKIP_MIME_TYPES:
                    all_files.append(file_meta)

            page_token = response.get("nextPageToken")
            if not page_token:
                break

    return all_files


def _download_file(service, file_meta: dict[str, Any]) -> tuple[bytes, str]:
    """Download a file from Google Drive. Returns (content_bytes, filename).

    For Google Workspace docs, exports to a standard format.
    For regular files, downloads the binary content.
    """
    mime = file_meta.get("mimeType", "")
    name = file_meta.get("name", "untitled")

    if mime in _EXPORT_MIME_MAP:
        export_mime, ext = _EXPORT_MIME_MAP[mime]
        # Ensure filename has the export extension
        if not name.lower().endswith(ext):
            name = f"{name}{ext}"
        request = service.files().export_media(fileId=file_meta["id"], mimeType=export_mime)
    else:
        request = service.files().get_media(fileId=file_meta["id"])

    # Stream download into memory
    from googleapiclient.http import MediaIoBaseDownload

    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)

    done = False
    while not done:
        _, done = downloader.next_chunk()

    return buffer.getvalue(), name


async def sync_google_drive_to_minio(
    *,
    source_id: uuid.UUID,
    config: dict[str, Any],
    bucket: str,
    connector_id: uuid.UUID | str | None = None,
) -> dict[str, Any]:
    """Sync files from a Google Drive folder into a MinIO bucket with full CRUD reflection.

    Performs a differential state sync:
      - ADD: New files in Google Drive are downloaded and uploaded to MinIO.
      - REPLACE/UPDATE: Modified files in Google Drive are updated in MinIO.
      - DELETE: Files deleted in Google Drive are removed from MinIO.

    Args:
        source_id: The source record's UUID.
        config: Connector config containing service_account_json and folder_url/folder_id.
        bucket: MinIO bucket name for this source.
        connector_id: Optional connector UUID for namespace isolation.

    Returns:
        dict with keys: files_synced, files_added, files_updated, files_deleted.
    """
    from src.shared.storage.s3_client import delete_object, head_object, list_objects

    # Extract service account credentials
    sa_json = config.get("service_account_json") or config.get("credentials_json")
    if isinstance(sa_json, str):
        sa_json = json.loads(sa_json)
    if not sa_json:
        raise ValueError("Missing service_account_json or credentials_json in connector config")

    # Extract folder ID from URL or direct ID
    folder_url = config.get("folder_url", "") or config.get("folder_id", "")
    if not folder_url:
        raise ValueError("Missing folder_url or folder_id in connector config")
    folder_id = _extract_folder_id(folder_url)

    logger.info(
        "gdrive_sync_starting source=%s connector=%s folder=%s bucket=%s",
        source_id, connector_id, folder_id, bucket,
    )

    # Ensure bucket exists
    await ensure_bucket(bucket)

    # Build Drive service
    service = _build_drive_service(sa_json)

    # List active files in Google Drive folder
    files = _list_files_in_folder(service, folder_id)
    remote_files_map: dict[str, dict[str, Any]] = {f["id"]: f for f in files}

    logger.info(
        "gdrive_remote_files source=%s connector=%s count=%d",
        source_id, connector_id, len(remote_files_map),
    )

    # Query all existing MinIO objects matching this source/connector
    minio_files_map: dict[str, list[Any]] = {}
    conn_str = str(connector_id) if connector_id else None
    existing_objects = await list_objects(bucket, prefix="")

    for obj in existing_objects:
        parts = obj.key.split("/")
        drive_file_id = None

        if len(parts) >= 4 and parts[0] in ["connectors", "gdrive-sync"]:
            drive_file_id = parts[2]
        else:
            # Fallback: check S3 object metadata
            try:
                head = await head_object(bucket, obj.key)
                meta = (head.get("Metadata") or head.get("metadata") or {}) if head else {}
                drive_file_id = meta.get("gdrive-file-id") or meta.get("gdrive_file_id")
            except Exception:
                pass

        if drive_file_id:
            minio_files_map.setdefault(drive_file_id, []).append(obj)

    files_added = 0
    files_updated = 0
    files_deleted = 0
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    for drive_id, file_meta in remote_files_map.items():
        remote_modified = file_meta.get("modifiedTime", "")
        try:
            content, filename = _download_file(service, file_meta)
            if not content:
                logger.warning(
                    "gdrive_empty_file source=%s file=%s name=%s",
                    source_id, drive_id, filename,
                )
                continue

            prefix_base = f"connectors/{conn_str}" if conn_str else f"gdrive-sync/{source_id}"
            target_key = f"{prefix_base}/{drive_id}/{filename}"

            existing_objs = minio_files_map.get(drive_id, [])
            target_obj_exists = any(o.key == target_key for o in existing_objs)

            needs_upload = not target_obj_exists
            is_update = False

            if target_obj_exists:
                head = await head_object(bucket, target_key)
                meta = (head.get("Metadata") or head.get("metadata") or {}) if head else {}
                old_modified = meta.get("remote-modified-at") or meta.get("remote_modified_at") or ""
                old_size = head.get("ContentLength") or head.get("content-length") or 0

                # Trigger update if modified timestamp or size changed
                if (old_modified and remote_modified and old_modified != remote_modified) or (old_size and len(content) != old_size):
                    needs_upload = True
                    is_update = True
            if needs_upload:
                await put_object(
                    bucket_name=bucket,
                    key=target_key,
                    data=content,
                    metadata={
                        "source-id": str(source_id),
                        "connector-id": str(conn_str) if conn_str else "",
                        "gdrive-file-id": drive_id,
                        "gdrive-mime-type": file_meta.get("mimeType", ""),
                        "remote-modified-at": remote_modified,
                        "sync-timestamp": timestamp,
                    },
                )
                if is_update:
                    files_updated += 1
                    logger.info("gdrive_file_updated source=%s key=%s", source_id, target_key)
                else:
                    files_added += 1
                    logger.info("gdrive_file_added source=%s key=%s", source_id, target_key)

            # Remove obsolete keys for this drive_id (e.g. old filename or old prefix)
            for obj in existing_objs:
                if obj.key != target_key:
                    try:
                        await delete_object(bucket, obj.key)
                        logger.info("gdrive_obsolete_key_removed source=%s key=%s", source_id, obj.key)
                    except Exception as exc:
                        logger.warning("gdrive_remove_obsolete_failed key=%s err=%s", obj.key, exc)

        except Exception as exc:
            logger.warning(
                "gdrive_file_sync_failed source=%s file=%s name=%s error=%s",
                source_id, drive_id, file_meta.get("name"), exc,
            )

    # 2. Handle DELETE (Files deleted in Drive must be deleted from MinIO)
    for drive_id, minio_objs in minio_files_map.items():
        if drive_id not in remote_files_map:
            for obj in minio_objs:
                try:
                    await delete_object(bucket, obj.key)
                    files_deleted += 1
                    logger.info("gdrive_file_deleted source=%s key=%s", source_id, obj.key)
                except Exception as exc:
                    logger.warning("gdrive_delete_failed source=%s key=%s error=%s", source_id, obj.key, exc)

    total_active = len(remote_files_map)
    logger.info(
        "gdrive_sync_completed source=%s connector=%s total_active=%d added=%d updated=%d deleted=%d",
        source_id, connector_id, total_active, files_added, files_updated, files_deleted,
    )
    return {
        "files_synced": total_active,
        "files_added": files_added,
        "files_updated": files_updated,
        "files_deleted": files_deleted,
    }
