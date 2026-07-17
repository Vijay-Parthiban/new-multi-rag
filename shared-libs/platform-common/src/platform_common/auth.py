"""Reusable FastAPI API-key authentication."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Paths that remain reachable when API_KEY is configured (probes / docs).
_PUBLIC_PATHS = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})


def make_verify_api_key(get_expected_key: Callable[[], str]) -> Callable[..., str]:
    """Build a FastAPI dependency that validates X-API-Key against get_expected_key()."""

    def verify_api_key(
        request: Request,
        api_key: str | None = Security(_api_key_header),
    ) -> str:
        if request.url.path in _PUBLIC_PATHS:
            return ""

        expected = get_expected_key()
        if not expected:
            return ""
        if not api_key or api_key != expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing API key",
            )
        return api_key

    return verify_api_key


def verify_api_key_value(expected: str, api_key: str | None, *, path: str = "") -> str:
    """Non-FastAPI helper for workers/clients validating a key value."""
    if path in _PUBLIC_PATHS:
        return ""
    if not expected:
        return ""
    if not api_key or api_key != expected:
        raise PermissionError("Invalid or missing API key")
    return api_key


def verify_api_key(
    request: Request,
    api_key: str | None = Security(_api_key_header),
    expected: str = "",
) -> str:
    """Validate X-API-Key; no-op when expected is empty. Prefer make_verify_api_key in apps."""
    if request.url.path in _PUBLIC_PATHS:
        return ""
    if not expected:
        return ""
    if not api_key or api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
    return api_key
