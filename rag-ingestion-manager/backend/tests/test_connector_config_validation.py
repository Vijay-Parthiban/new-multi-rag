"""Guard for the NiFi connector config contract.

The validator decides whether a connector ever syncs. Its required fields MUST
match the keys the NiFi sync routines read, or the connector silently never
copies files into MinIO.
"""

from src.ingestion_service.core.airbyte_connector import validate_airbyte_connector_config


def test_s3_accepts_the_keys_the_ui_sends():
    ok, err = validate_airbyte_connector_config(
        "s3",
        {
            "bucket": "my-bucket",
            "access_key_id": "AKIAEXAMPLE",
            "secret_access_key": "secret",
            "region": "us-east-1",
            "prefix": "docs/",
        },
    )
    assert ok is True, err


def test_s3_rejects_missing_bucket():
    ok, err = validate_airbyte_connector_config(
        "s3", {"access_key_id": "a", "secret_access_key": "b"}
    )
    assert ok is False
    assert "bucket" in err


def test_s3_rejects_incomplete_credentials():
    ok, err = validate_airbyte_connector_config("s3", {"bucket": "b", "access_key_id": "a"})
    assert ok is False
    assert "secret_access_key" in err


def test_azure_accepts_connection_string_only():
    ok, err = validate_airbyte_connector_config(
        "azure_blob", {"container_name": "docs", "connection_string": "DefaultEndpointsProtocol=https;..."}
    )
    assert ok is True, err


def test_azure_accepts_account_name_and_key():
    ok, err = validate_airbyte_connector_config(
        "azure_blob",
        {"container_name": "docs", "account_name": "acct", "account_key": "key"},
    )
    assert ok is True, err


def test_azure_rejects_missing_auth():
    ok, err = validate_airbyte_connector_config("azure_blob", {"container_name": "docs"})
    assert ok is False
    assert "connection_string" in err


def test_google_drive_requires_a_folder():
    ok, err = validate_airbyte_connector_config("google_drive", {"folder_url": ""})
    assert ok is False
    assert "folder_url" in err

    ok, _ = validate_airbyte_connector_config(
        "google_drive", {"folder_url": "https://drive.google.com/drive/folders/abc"}
    )
    assert ok is True
