"""Airbyte connector runner — sync a source, write output to MinIO.

Uses the Airbyte Python CDK to run source connectors and write
the resulting records as newline-delimited JSON files to the
source's dedicated MinIO bucket.
"""

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aioboto3
from botocore.exceptions import ClientError

from pathway_worker.settings import get_settings

logger = logging.getLogger(__name__)

# ── Airbyte connector imports (lazy, installed as extras) ────────────

_AIRBYTE_CONNECTORS: dict[str, Any] = {}


def _import_connector(connector_type: str) -> Any | None:
    """Lazy-import an Airbyte source connector class.

    Returns None if the connector package is not installed.
    """
    if connector_type in _AIRBYTE_CONNECTORS:
        return _AIRBYTE_CONNECTORS[connector_type]

    # Map connector_type -> Airbyte Source class paths
    # These come from the airbyte-connectors package or individual connector packages
    connector_map: dict[str, tuple[str, str]] = {
        "google_drive": ("source_google_drive", "SourceGoogleDrive"),
        "gcs": ("source_gcs", "SourceGcs"),
        "s3": ("source_s3", "SourceS3"),
        "azure_blob": ("source_azure_blob_storage", "SourceAzureBlobStorage"),
        "onedrive": ("source_onedrive", "SourceOnedrive"),
        "dropbox": ("source_dropbox", "SourceDropbox"),
        "postgres": ("source_postgres", "SourcePostgres"),
        "mysql": ("source_mysql", "SourceMysql"),
        "mongodb": ("source_mongodb", "SourceMongodb"),
        "github": ("source_github", "SourceGithub"),
        "slack": ("source_slack", "SourceSlack"),
        "confluence": ("source_confluence", "SourceConfluence"),
        "sharepoint": ("source_sharepoint", "SourceSharepoint"),
        "sftp": ("source_sftp", "SourceSftp"),
        "http_api": ("source_http_api", "SourceHttpApi"),
    }

    mapping = connector_map.get(connector_type)
    if not mapping:
        logger.warning("connector_unknown type=%s", connector_type)
        return None

    module_name, class_name = mapping
    try:
        module = __import__(module_name, fromlist=[class_name])
        cls = getattr(module, class_name)
        _AIRBYTE_CONNECTORS[connector_type] = cls
        logger.info("connector_loaded type=%s module=%s", connector_type, module_name)
        return cls
    except ImportError:
        logger.warning(
            "connector_not_installed type=%s module=%s — install the airbyte source package",
            connector_type,
            module_name,
        )
        _AIRBYTE_CONNECTORS[connector_type] = None
        return None


# ── MinIO output helpers ─────────────────────────────────────────────

def _s3_client():
    settings = get_settings()
    session = aioboto3.Session()
    return session.client(
        "s3",
        endpoint_url=f"http://{settings.minio_endpoint}",
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        use_ssl=settings.minio_use_ssl.lower() == "true",
    )


async def _ensure_bucket(bucket: str) -> None:
    """Create bucket if it doesn't exist."""
    async with _s3_client() as s3:
        try:
            await s3.head_bucket(Bucket=bucket)
        except ClientError:
            await s3.create_bucket(Bucket=bucket)
            logger.info("bucket_created bucket=%s", bucket)


async def _upload_file(bucket: str, key: str, data: bytes) -> None:
    async with _s3_client() as s3:
        await s3.put_object(Bucket=bucket, Key=key, Body=data)


# ── Airbyte sync runner ──────────────────────────────────────────────

def _records_to_jsonl(records: list[dict[str, Any]]) -> bytes:
    """Convert a list of Airbyte records to newline-delimited JSON bytes."""
    lines = [json.dumps(r, default=str) for r in records]
    return "\n".join(lines).encode("utf-8")


async def run_connector_sync(
    *,
    source_id: uuid.UUID,
    connector_type: str,
    config: dict[str, Any],
    bucket: str,
    output_dir: Path,
) -> int:
    """Run an Airbyte source connector and write output to MinIO.

    Args:
        source_id: Source record UUID.
        connector_type: One of the CONNECTOR_OPTIONS ids (e.g. "google_drive").
        config: Connector-specific configuration dict.
        bucket: MinIO bucket name for this source.
        output_dir: Local temp directory for connector output.

    Returns:
        Number of files written to MinIO.
    """
    ConnectorClass = _import_connector(connector_type)
    if ConnectorClass is None:
        logger.error(
            "connector_unavailable source=%s type=%s",
            source_id, connector_type,
        )
        return 0

    logger.info(
        "connector_sync_starting source=%s type=%s",
        source_id, connector_type,
    )

    # Ensure the output bucket exists
    await _ensure_bucket(bucket)

    # Run the Airbyte source connector
    try:
        source = ConnectorClass()
        # Discover the catalog (what streams are available)
        catalog = source.discover(config)

        # Read records from all available streams
        records: dict[str, list[dict[str, Any]]] = {}
        for configured_stream in catalog.streams:
            stream_name = configured_stream.stream.name
            try:
                stream_records = list(
                    source.read(config, catalog, [configured_stream])
                )
                if stream_records:
                    records[stream_name] = [
                        r.record.data if hasattr(r, "record") else r
                        for r in stream_records
                    ]
                    logger.info(
                        "stream_records source=%s stream=%s count=%d",
                        source_id, stream_name, len(records[stream_name]),
                    )
            except Exception as exc:
                logger.warning(
                    "stream_failed source=%s stream=%s error=%s",
                    source_id, stream_name, exc,
                )
    except Exception as exc:
        logger.exception(
            "connector_sync_failed source=%s type=%s error=%s",
            source_id, connector_type, exc,
        )
        return 0

    if not records:
        logger.info("connector_sync_no_records source=%s", source_id)
        return 0

    # Write each stream's records as a JSONL file in MinIO
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    sync_id = uuid.uuid4().hex[:12]
    files_written = 0

    for stream_name, stream_records in records.items():
        data = _records_to_jsonl(stream_records)
        # Key:  pathway-syncs/{source_id}/{sync_id}/{stream_name}_{timestamp}.jsonl
        key = f"pathway-syncs/{source_id}/{sync_id}/{stream_name}_{timestamp}.jsonl"

        await _upload_file(bucket, key, data)
        files_written += 1

        logger.info(
            "file_uploaded bucket=%s key=%s records=%d size=%d",
            bucket, key, len(stream_records), len(data),
        )

    logger.info(
        "connector_sync_complete source=%s type=%s files=%d",
        source_id, connector_type, files_written,
    )
    return files_written