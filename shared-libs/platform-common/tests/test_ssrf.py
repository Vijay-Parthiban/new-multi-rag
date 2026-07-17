"""Unit tests for SSRF URL validation."""
from __future__ import annotations

import pytest

from platform_common.ssrf import UnsafeURLError, validate_public_http_url


def test_rejects_empty() -> None:
    with pytest.raises(UnsafeURLError):
        validate_public_http_url("")


def test_rejects_non_http_scheme() -> None:
    with pytest.raises(UnsafeURLError, match="scheme"):
        validate_public_http_url("ftp://example.com")


def test_rejects_localhost_by_default() -> None:
    with pytest.raises(UnsafeURLError):
        validate_public_http_url("http://localhost/admin")


def test_rejects_private_ip_literal() -> None:
    with pytest.raises(UnsafeURLError):
        validate_public_http_url("http://127.0.0.1/")
    with pytest.raises(UnsafeURLError):
        validate_public_http_url("http://10.0.0.5/internal")
    with pytest.raises(UnsafeURLError):
        validate_public_http_url("http://169.254.169.254/latest/meta-data/")


def test_allows_private_when_override() -> None:
    assert (
        validate_public_http_url("http://127.0.0.1/", allow_private=True)
        == "http://127.0.0.1/"
    )


def test_allows_public_example() -> None:
    # example.com is reserved documentation domain; resolve may still work
    url = validate_public_http_url("https://example.com/path")
    assert url == "https://example.com/path"


def test_rejects_credentials_in_url() -> None:
    with pytest.raises(UnsafeURLError, match="credentials"):
        validate_public_http_url("https://user:pass@example.com/")
