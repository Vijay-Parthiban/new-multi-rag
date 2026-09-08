from __future__ import annotations

import logging
from typing import Any
import httpx

logger = logging.getLogger(__name__)


def run_guardrails_check(
    text: str,
    guards: list[str],
    guardrails_url: str = "http://localhost:8002",
    timeout_s: float = 5.0,
    settings: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    base_url = guardrails_url.rstrip("/")

    with httpx.Client(timeout=timeout_s) as client:
        for guard in guards:
            try:
                url = f"{base_url}/parse/{guard}"
                resp = client.post(url, json={"llm_output": text, "metadata": settings or {}})
                if resp.status_code == 200:
                    results[guard] = resp.json()
                else:
                    results[guard] = {
                        "validation_passed": True,
                        "error": f"HTTP {resp.status_code}",
                        "detail": resp.text,
                    }
            except Exception as exc:
                results[guard] = {
                    "validation_passed": True,
                    "error": str(exc),
                    "detail": "Guardrails connection error",
                }

    return results


def check_blocked(results: dict[str, dict[str, Any]]) -> tuple[bool, str | None]:
    for guard, res in results.items():
        if not res.get("validation_passed", True):
            return True, guard
    return False, None
