from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# The PII validator was called pii_check before the validator catalog existed. Rename it
# wherever it appears so an old row keeps working without a data migration.
LEGACY_GUARD_IDS = {"pii_check": "detect_pii"}

# Legacy flat settings keys, mapped to the validator that now owns them.
_LEGACY_SETTING_KEYS = {"banned_words": "ban_list", "pii_entities": "detect_pii"}


def upgrade_settings(raw: Any, guards: list[str]) -> dict[str, dict[str, Any]]:
    """Return settings in the per-validator shape, keyed by the given guard ids.

    Accepts the old flat shape (``{"banned_words": [...], "pii_entities": [...]}``) and the
    current nested shape (``{"ban_list": {"banned_words": [...]}}``). The settings column is
    JSONB, so this runs on read and on write and no migration is needed.
    """
    if not isinstance(raw, dict):
        return {guard: {} for guard in guards}

    nested: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if key in _LEGACY_SETTING_KEYS:
            owner = _LEGACY_SETTING_KEYS[key]
            if value:
                nested.setdefault(owner, {})[key] = value
            continue
        if isinstance(value, dict):
            nested[LEGACY_GUARD_IDS.get(key, key)] = dict(value)

    return {guard: nested.get(guard, {}) for guard in guards}


def build_validator_specs(guards: list[str], settings: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Turn a config's guard list and settings into the payload the service expects.

    `settings` is keyed by validator id, and each value holds that validator's parameters plus
    an optional `on_fail`. A validator with no entry still runs, with its catalog defaults.
    """
    normalized = upgrade_settings(settings, guards)
    specs: list[dict[str, Any]] = []
    for guard in guards:
        entry = normalized.get(guard) or {}
        params = {k: v for k, v in entry.items() if k != "on_fail"}
        specs.append(
            {
                "id": guard,
                "params": params,
                "on_fail": str(entry.get("on_fail") or "noop"),
            }
        )
    return specs


def run_guardrails_check(
    text: str,
    guards: list[str],
    guardrails_url: str = "http://localhost:18000",
    timeout_s: float = 15.0,
    settings: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Validate text against guardrails-service for the given validator ids.

    Returns one entry per validator id with `validation_passed`, `error` and `detail`.
    A transport failure or a rejected configuration reports `validation_passed: True` with a
    non-null `error`, so a misconfigured guard never blocks every chat turn. The trace records
    the error.
    """
    if not guards:
        return {}

    # A config written before the catalog existed may still name pii_check.
    guards = [LEGACY_GUARD_IDS.get(g, g) for g in guards]

    base_url = guardrails_url.rstrip("/")
    payload = {
        "text": text,
        "validators": build_validator_specs(guards, settings),
    }

    def _all_guards(**extra: Any) -> dict[str, dict[str, Any]]:
        return {guard: {**extra} for guard in guards}

    try:
        with httpx.Client(timeout=timeout_s) as client:
            resp = client.post(f"{base_url}/validate", json=payload)
    except Exception as exc:
        logger.error("Guardrails service is unreachable at %s: %s", base_url, exc)
        return _all_guards(validation_passed=True, error=str(exc), detail=None)

    if resp.status_code != 200:
        detail = resp.text[:500]
        logger.error("Guardrails service returned HTTP %s: %s", resp.status_code, detail)
        return _all_guards(
            validation_passed=True,
            error=f"HTTP {resp.status_code}",
            detail=detail,
        )

    try:
        body = resp.json()
        results = body.get("results") or {}
    except Exception as exc:
        logger.error("Guardrails service returned an unreadable body: %s", exc)
        return _all_guards(validation_passed=True, error=str(exc), detail=None)

    # Report a missing validator rather than silently treating it as passed.
    for guard in guards:
        results.setdefault(
            guard,
            {"validation_passed": True, "error": "validator missing from the response", "detail": None},
        )
    return results


def check_blocked(results: dict[str, dict[str, Any]]) -> tuple[bool, str | None]:
    """Check if any guard blocked the text."""
    for guard, res in results.items():
        if not res.get("validation_passed", True):
            return True, guard
    return False, None
