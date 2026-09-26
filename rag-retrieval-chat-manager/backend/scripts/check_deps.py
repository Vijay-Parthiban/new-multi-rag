"""Probe every runtime dependency of the retrieval service from inside its container.

Run it there, so it exercises the real network path:

    docker cp scripts/check_deps.py backend-rag-api-1:/tmp/check_deps.py
    docker exec backend-rag-api-1 python /tmp/check_deps.py

Every URL comes from the resolved settings, so this also proves the settings are
wired to the values the container was given. Exit 0 when every dependency answers.
"""

from __future__ import annotations

import os
import socket
import sys
from urllib.parse import urlparse

import httpx

from rag_shared.config import get_settings

settings = get_settings()
failures: list[str] = []
checks = 0


def report(label: str, ok: bool, detail: str) -> None:
    global checks
    checks += 1
    print(f"  {'ok  ' if ok else 'FAIL'} {label:28} {detail}")
    if not ok:
        failures.append(label)


def http(label: str, url: str, expect: tuple[int, ...] = (200,)) -> None:
    if not url:
        report(label, False, "not configured (empty)")
        return
    try:
        r = httpx.get(url, timeout=15.0)
        report(label, r.status_code in expect, f"{r.status_code} {url}")
    except Exception as exc:  # noqa: BLE001
        report(label, False, f"{type(exc).__name__} {url}")


def tcp(label: str, url: str) -> None:
    """A TCP connect, for services with no cheap HTTP endpoint."""
    if not url:
        report(label, False, "not configured (empty)")
        return
    parsed = urlparse(url if "://" in url else f"//{url}", scheme="tcp")
    host, port = parsed.hostname, parsed.port or 0
    if not host or not port:
        report(label, False, f"cannot parse {url}")
        return
    try:
        with socket.create_connection((host, port), timeout=10):
            report(label, True, f"tcp {host}:{port}")
    except Exception as exc:  # noqa: BLE001
        report(label, False, f"{type(exc).__name__} {host}:{port}")


print("resolved settings:")
for key in (
    "database_url",
    "redis_url",
    "qdrant_kp_url",
    "qdrant_url",
    "opensearch_url",
    "ingestion_service_url",
    "litellm_base_url",
    "guardrails_url",
):
    print(f"  {key:32} {getattr(settings, key, '<ABSENT>')}")

# The OTLP exporter reads these from the environment directly, not from Settings.
print(f"  {'OTEL_EXPORTER_OTLP_ENDPOINT':32} {os.environ.get('OTEL_EXPORTER_OTLP_ENDPOINT', '<unset>')}")

print("\ndependencies:")
http("ingestion API", f"{settings.ingestion_service_url.rstrip('/')}/api/knowledge-products")
# The proxy answers 401 without a key, which still proves it is reachable.
http("litellm proxy", f"{settings.litellm_base_url.rstrip('/')}/v1/models", expect=(200, 401))
http("guardrails service", f"{settings.guardrails_url.rstrip('/')}/health-check")
http("opensearch", settings.opensearch_url)
tcp("postgres", settings.database_url)
tcp("redis", settings.redis_url)
tcp("qdrant (kp, 6335)", settings.qdrant_kp_url or "")
tcp("otel collector", os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", ""))

print(f"\n{checks} checks, {len(failures)} failure(s)")
if failures:
    print("failing: " + ", ".join(failures))
sys.exit(1 if failures else 0)
