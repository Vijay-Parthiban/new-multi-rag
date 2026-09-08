"""
Pathway Airbyte Connector Integration

This module provides integration with Pathway's Airbyte connector support,
enabling data ingestion from 350+ Airbyte sources into MinIO buckets.

Pathway Documentation:
- https://pathway.com/developers/api-docs/pathway-io/airbyte
- https://pathway.com/developers/user-guide/connect/connectors/airbyte-connectors/

Airbyte Connector Documentation:
- https://docs.airbyte.com/integrations/
"""

import json
import logging
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, UTC

from sqlalchemy.ext.asyncio import AsyncSession
from src.shared.db.models import Source, SourceConnector
from src.shared.storage.s3_client import get_minio_client

logger = logging.getLogger(__name__)


# Airbyte connector type mappings to Airbyte source names
AIRBYTE_CONNECTOR_MAP = {
    "google_drive": "source-google-drive",
    "s3": "source-s3",
    "gcs": "source-gcs",
    "azure_blob": "source-azure-blob-storage",
    "azure": "source-azure-blob-storage",
    "google_sheets": "source-google-sheets",
    "onedrive": "source-microsoft-onedrive",
    "microsoft_onedrive": "source-microsoft-onedrive",
    "sharepoint": "source-microsoft-sharepoint",
    "postgres": "source-postgres",
    "local_folder": None,  # Native Pathway connector
    "local_dir": None,     # Native Pathway connector
}


def get_airbyte_config_for_connector(
    connector_type: str,
    config: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    Transform frontend connector config to Airbyte connector config format.
    
    Each Airbyte connector has its own configuration schema. This function
    maps our generic connector config to the specific Airbyte connector format.
    
    Args:
        connector_type: Type of connector (google_drive, s3, postgres, etc.)
        config: Configuration dictionary from frontend
        
    Returns:
        Airbyte-compatible configuration dictionary, or None if not Airbyte connector
    """
    
    if connector_type == "google_drive":
        # Airbyte source-google-drive configuration
        # https://docs.airbyte.com/integrations/sources/google-drive
        return {
            "credentials": {
                "auth_type": "Service",
                "service_account_info": config.get("service_account_json", config.get("credentials_json", ""))
            },
            "folder_url": config.get("folder_url", config.get("folder_id", "")),
            "stream_name": config.get("stream_name", "google_drive_files")
        }
    
    elif connector_type == "s3":
        # Airbyte source-s3 configuration
        # https://docs.airbyte.com/integrations/sources/s3
        return {
            "bucket": config.get("bucket", ""),
            "aws_access_key_id": config.get("aws_access_key_id"),
            "aws_secret_access_key": config.get("aws_secret_access_key"),
            "region_name": config.get("region", "us-east-1"),
            "path_prefix": config.get("prefix", ""),
            "format": {
                "filetype": "unstructured"  # Supports PDF, DOCX, etc.
            },
            "provider": {
                "bucket": config.get("bucket", ""),
                "aws_access_key_id": config.get("aws_access_key_id"),
                "aws_secret_access_key": config.get("aws_secret_access_key"),
                "region_name": config.get("region", "us-east-1"),
                "path_prefix": config.get("prefix", "")
            }
        }
    
    elif connector_type in ["gcs", "google_cloud_storage"]:
        # Airbyte source-gcs configuration
        # https://docs.airbyte.com/integrations/sources/gcs
        return {
            "bucket": config.get("bucket_name", config.get("bucket", "")),
            "service_account_json": config.get("credentials_json", ""),
            "path_prefix": config.get("prefix", ""),
            "format": {
                "filetype": "unstructured"
            }
        }
    
    elif connector_type in ["azure_blob", "azure"]:
        # Airbyte source-azure-blob-storage configuration
        # https://docs.airbyte.com/integrations/sources/azure-blob-storage
        return {
            "azure_blob_storage_account_name": config.get("account_name", ""),
            "azure_blob_storage_account_key": config.get("account_key", ""),
            "azure_blob_storage_container_name": config.get("container_name", ""),
            "azure_blob_storage_blobs_prefix": config.get("prefix", ""),
            "format": {
                "filetype": "unstructured"
            }
        }
    
    elif connector_type == "google_sheets":
        # Airbyte source-google-sheets configuration
        # https://docs.airbyte.com/integrations/sources/google-sheets
        return {
            "credentials": {
                "auth_type": "Service",
                "service_account_info": config.get("credentials_json", "")
            },
            "spreadsheet_id": config.get("spreadsheet_id", ""),
            "names_conversion": True
        }
    
    elif connector_type in ["onedrive", "microsoft_onedrive"]:
        # Airbyte source-microsoft-onedrive configuration
        # https://docs.airbyte.com/integrations/sources/microsoft-onedrive
        return {
            "credentials": {
                "auth_type": "Client",
                "tenant_id": config.get("tenant_id", ""),
                "client_id": config.get("client_id", ""),
                "client_secret": config.get("client_secret", "")
            },
            "drive_name": config.get("drive_id", ""),
            "folder_path": config.get("folder_path", ""),
            "search_scope": "ALL"
        }
    
    elif connector_type == "sharepoint":
        # Airbyte source-microsoft-sharepoint configuration
        # https://docs.airbyte.com/integrations/sources/microsoft-sharepoint
        return {
            "credentials": {
                "auth_type": "Client",
                "tenant_id": config.get("tenant_id", ""),
                "client_id": config.get("client_id", ""),
                "client_secret": config.get("client_secret", "")
            },
            "site_url": config.get("site_url", ""),
            "document_library": config.get("document_library", ""),
            "folder_path": config.get("folder_path", ""),
            "search_scope": "ACCESSIBLE"
        }
    
    elif connector_type == "postgres":
        # Airbyte source-postgres configuration
        # https://docs.airbyte.com/integrations/sources/postgres
        return {
            "host": config.get("host", "localhost"),
            "port": config.get("port", 5432),
            "database": config.get("database", ""),
            "username": config.get("user", config.get("username", "")),
            "password": config.get("password", ""),
            "schemas": config.get("schemas", ["public"]),
            "replication_method": {
                "method": "Standard"
            }
        }
    
    # Not an Airbyte connector (e.g., local_folder handled separately)
    return None


def get_airbyte_streams_for_connector(connector_type: str) -> List[str]:
    """
    Get default stream names for each Airbyte connector type.
    
    Pathway requires explicit stream names to read from Airbyte connectors.
    
    Args:
        connector_type: Type of connector
        
    Returns:
        List of stream names to read
    """
    
    stream_map = {
        "google_drive": ["files"],
        "s3": ["stream"],
        "gcs": ["stream"],
        "azure_blob": ["stream"],
        "azure": ["stream"],
        "google_sheets": ["sheet"],
        "onedrive": ["files"],
        "microsoft_onedrive": ["files"],
        "sharepoint": ["files"],
        "postgres": ["public"]  # Will be overridden by schema config
    }
    
    return stream_map.get(connector_type, ["stream"])


async def sync_airbyte_connector_to_minio(
    db: AsyncSession,
    source: Source,
    connector: SourceConnector,
    minio_bucket: str
) -> Dict[str, Any]:
    """
    Sync data from an Airbyte connector to MinIO using Pathway.
    
    This function:
    1. Creates a temporary Airbyte config file
    2. Invokes Pathway's pw.io.airbyte.read() function
    3. Downloads files from the Airbyte stream
    4. Uploads them to the MinIO bucket
    5. Returns sync statistics
    
    Args:
        db: Database session
        source: Source model instance
        connector: SourceConnector model instance
        minio_bucket: MinIO bucket name to upload files to
        
    Returns:
        Dictionary with sync statistics (files_synced, bytes_transferred, etc.)
    """
    
    connector_type = connector.connector_type
    config = connector.config or {}
    
    # Check if this is an Airbyte connector
    airbyte_source = AIRBYTE_CONNECTOR_MAP.get(connector_type)
    if not airbyte_source:
        logger.warning(
            "Not an Airbyte connector, skipping connector_type=%s",
            connector_type
        )
        return {"error": "Not an Airbyte connector"}
    
    # Transform config to Airbyte format
    airbyte_config = get_airbyte_config_for_connector(connector_type, config)
    if not airbyte_config:
        logger.error(
            "Failed to generate Airbyte config connector_type=%s",
            connector_type
        )
        return {"error": "Invalid configuration"}
    
    # Create temporary config file for Pathway
    with tempfile.NamedTemporaryFile(
        mode='w',
        suffix='.json',
        delete=False,
        encoding='utf-8'
    ) as config_file:
        json.dump(airbyte_config, config_file, indent=2)
        config_file_path = config_file.name
    
    try:
        # Get stream names for this connector
        streams = get_airbyte_streams_for_connector(connector_type)
        
        logger.info(
            "Starting Airbyte sync source=%s connector=%s type=%s streams=%s",
            source.id,
            connector.id,
            connector_type,
            streams
        )
        
        # Execute Pathway Airbyte sync
        # NOTE: Pathway's pw.io.airbyte.read() is a synchronous blocking operation
        # For production, this should run in a separate worker process
        result = await _execute_pathway_airbyte_sync(
            config_file_path=config_file_path,
            airbyte_source=airbyte_source,
            streams=streams,
            minio_bucket=minio_bucket,
            source_id=str(source.id),
            connector_id=str(connector.id)
        )
        
        logger.info(
            "Airbyte sync completed source=%s connector=%s files=%d",
            source.id,
            connector.id,
            result.get("files_synced", 0)
        )
        
        return result
        
    except Exception as exc:
        logger.error(
            "Airbyte sync failed source=%s connector=%s error=%s",
            source.id,
            connector.id,
            str(exc),
            exc_info=True
        )
        raise
    finally:
        # Clean up temporary config file
        try:
            Path(config_file_path).unlink()
        except Exception:
            pass


async def _execute_pathway_airbyte_sync(
    config_file_path: str,
    airbyte_source: str,
    streams: List[str],
    minio_bucket: str,
    source_id: str,
    connector_id: str
) -> Dict[str, Any]:
    """
    Execute Pathway Airbyte sync and upload results to MinIO.
    
    This function runs Pathway's pw.io.airbyte.read() to fetch data from
    the Airbyte connector and uploads files to MinIO.
    
    NOTE: This is a placeholder implementation. In production, you would:
    1. Install pathway: pip install pathway
    2. Import: import pathway as pw
    3. Run: table = pw.io.airbyte.read(config_file_path, streams)
    4. Process the table and extract file content
    5. Upload to MinIO
    
    For now, we provide the integration structure and config generation.
    
    Args:
        config_file_path: Path to Airbyte config JSON file
        airbyte_source: Airbyte source name (e.g., "source-google-drive")
        streams: List of stream names to read
        minio_bucket: MinIO bucket to upload files to
        source_id: Source UUID
        connector_id: Connector UUID
        
    Returns:
        Dictionary with sync statistics
    """
    
    # TODO: Implement actual Pathway Airbyte sync
    # Example Pathway code (to be implemented):
    #
    # import pathway as pw
    #
    # # Read from Airbyte connector
    # table = pw.io.airbyte.read(
    #     config_file_path=config_file_path,
    #     streams=streams,
    #     execution_type="local",
    #     mode="streaming"
    # )
    #
    # # Process table and extract file content
    # files_synced = 0
    # bytes_transferred = 0
    #
    # # Upload to MinIO
    # minio_client = get_minio_client()
    # for row in table:
    #     file_content = row.get("content")
    #     file_name = row.get("name")
    #     object_name = f"{source_id}/{connector_id}/{file_name}"
    #     
    #     minio_client.put_object(
    #         bucket_name=minio_bucket,
    #         object_name=object_name,
    #         data=BytesIO(file_content),
    #         length=len(file_content)
    #     )
    #     
    #     files_synced += 1
    #     bytes_transferred += len(file_content)
    #
    # return {
    #     "files_synced": files_synced,
    #     "bytes_transferred": bytes_transferred,
    #     "sync_time": datetime.now(UTC).isoformat()
    # }
    
    logger.warning(
        "Pathway Airbyte sync not yet implemented - config generated at %s",
        config_file_path
    )
    
    # Return placeholder result
    return {
        "files_synced": 0,
        "bytes_transferred": 0,
        "sync_time": datetime.now(UTC).isoformat(),
        "status": "config_generated",
        "config_path": config_file_path,
        "airbyte_source": airbyte_source,
        "streams": streams
    }


def validate_airbyte_connector_config(
    connector_type: str,
    config: Dict[str, Any]
) -> tuple[bool, Optional[str]]:
    """
    Validate connector configuration before sync.
    
    Args:
        connector_type: Type of connector
        config: Configuration dictionary
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    
    if connector_type == "google_drive":
        if not (config.get("folder_url") or config.get("folder_id")):
            return False, "Missing required field: folder_url or folder_id"
        if not (config.get("service_account_json") or config.get("credentials_json")):
            return False, "Missing required field: service_account_json or credentials_json"
        return True, None

    # Required fields for each connector type
    required_fields = {
        "s3": ["bucket", "aws_access_key_id", "aws_secret_access_key"],
        "gcs": ["bucket_name", "credentials_json"],
        "azure_blob": ["account_name", "container_name"],
        "azure": ["account_name", "container_name"],
        "google_sheets": ["spreadsheet_id", "credentials_json"],
        "onedrive": ["client_id", "client_secret", "tenant_id"],
        "microsoft_onedrive": ["client_id", "client_secret", "tenant_id"],
        "sharepoint": ["site_url", "client_id", "client_secret", "tenant_id"],
        "postgres": ["host", "database", "user", "password"]
    }

    required = required_fields.get(connector_type, [])

    for field in required:
        if not config.get(field):
            return False, f"Missing required field: {field}"

    return True, None
