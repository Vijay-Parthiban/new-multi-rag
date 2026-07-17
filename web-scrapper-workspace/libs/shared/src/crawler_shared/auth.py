"""Global API key authentication dependency for FastAPI."""
from __future__ import annotations

from platform_common.auth import make_verify_api_key

from crawler_shared.config import get_settings

verify_api_key = make_verify_api_key(lambda: get_settings().api_key)
