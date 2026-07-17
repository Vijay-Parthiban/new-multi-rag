"""SSRF guards for user-supplied crawl/scrape seed URLs."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeURLError(ValueError):
    """Raised when a URL targets a disallowed scheme, host, or private address."""


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_public_http_url(url: str, *, allow_private: bool = False) -> str:
    """Validate that ``url`` is http(s) and does not resolve to a private/internal address.

    When ``allow_private`` is True (local/dev override), only scheme checks apply.
    Returns the stripped URL on success; raises ``UnsafeURLError`` otherwise.
    """
    cleaned = (url or "").strip()
    if not cleaned:
        raise UnsafeURLError("URL must not be empty")

    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError("URL scheme must be http or https")
    if not parsed.hostname:
        raise UnsafeURLError("URL must include a hostname")
    if parsed.username or parsed.password:
        raise UnsafeURLError("URL must not include credentials")

    host = parsed.hostname.lower()
    if host in {"localhost", "metadata.google.internal"}:
        if not allow_private:
            raise UnsafeURLError(f"Host '{host}' is not allowed")
        return cleaned

    if allow_private:
        return cleaned

    try:
        # Literal IP in the hostname
        ip = ipaddress.ip_address(host)
        if _is_blocked_ip(ip):
            raise UnsafeURLError(f"IP address '{host}' is not allowed")
        return cleaned
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Could not resolve host '{host}'") from exc

    if not infos:
        raise UnsafeURLError(f"Could not resolve host '{host}'")

    for info in infos:
        sockaddr = info[4]
        ip = ipaddress.ip_address(sockaddr[0])
        if _is_blocked_ip(ip):
            raise UnsafeURLError(
                f"Host '{host}' resolves to blocked address '{ip}'"
            )

    return cleaned
