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


# The rails a prompt template governs. The template states how this pipeline must behave, so
# NeMo checks every turn against it even when the pipeline carries no guardrails config.
# `template_scope` reads the template as the scope and blocks what falls outside it. The two
# self checks keep their own policy: template prose written for the model is a poor blocking
# rule, and feeding it to them blocked valid in-scope answers.
TEMPLATE_RAIL_IDS: tuple[str, ...] = ("template_scope",)


def template_guardrails(
    template: str | None,
    guards: list[str],
    settings: dict[str, Any] | None = None,
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """The rails a prompt template implies, for every one of them that has no policy of its own.

    The template text becomes the rail's ``policy``, which the engine appends to that rail's own
    instructions, so the declared behaviour is what the judge checks the turn against. A rail the
    config names with a policy keeps that policy: the explicit choice wins. A rail the config
    names with an empty policy is filled in, because an empty scope says nothing and would leave
    the rail inert while it still counted as configured.

    Returns the rail ids to add and the settings to merge, in the shape a guard config stores
    them.
    """
    policy = (template or "").strip()
    if not policy:
        return [], {}

    configured = settings or {}
    add: list[str] = []
    filled: dict[str, dict[str, Any]] = {}
    for rail in TEMPLATE_RAIL_IDS:
        entry = dict(configured.get(rail) or {})
        if str(entry.get("policy") or "").strip():
            continue
        # A rail the config does not name has to be added; a rail it names is already in the
        # list, and adding it again would give the engine two flows with the same name.
        if rail not in guards:
            add.append(rail)
        entry["policy"] = policy
        entry.setdefault("model", "")
        entry.setdefault("on_fail", "noop")
        filled[rail] = entry
    return add, filled


def run_guardrails_phase(
    text: str,
    guards: list[str],
    guardrails_url: str = "http://localhost:18000",
    timeout_s: float = 15.0,
    settings: dict[str, Any] | None = None,
    *,
    phase: str = "both",
    query: str | None = None,
    answer: str | None = None,
    chunks: list[str] | None = None,
) -> dict[str, Any]:
    """Validate one phase against guardrails-service and return its whole answer.

    Keys: `results` (one entry per guard id, each with `validation_passed`, `error`, `detail`
    and, on the engine path, `ms`), `blocked`, `blocked_by`, `chunks` (the passages with masked
    text, from the retrieval phase, else None), `text` (the answer with masked text, from an
    output phase whose rail repairs, else None) and `skipped` (the phase had nothing to run).

    A transport failure or a rejected configuration reports every guard as passed with a
    non-null `error`, so a misconfigured guard never blocks every chat turn. The trace records
    the error.
    """
    if not guards:
        return {
            "results": {},
            "blocked": False,
            "blocked_by": None,
            "chunks": None,
            "text": None,
            "skipped": True,
        }

    # A config written before the catalog existed may still name pii_check.
    guards = [LEGACY_GUARD_IDS.get(g, g) for g in guards]

    base_url = guardrails_url.rstrip("/")
    payload: dict[str, Any] = {
        "text": text,
        "phase": phase,
        "validators": build_validator_specs(guards, settings),
    }
    # Only send what the caller has: an empty passage list must not look like a passage list.
    if query is not None:
        payload["query"] = query
    if answer is not None:
        payload["answer"] = answer
    if chunks:
        payload["chunks"] = chunks

    def _fail(**extra: Any) -> dict[str, Any]:
        return {
            "results": {guard: {**extra} for guard in guards},
            "blocked": False,
            "blocked_by": None,
            "chunks": None,
            "text": None,
            "skipped": False,
        }

    try:
        with httpx.Client(timeout=timeout_s) as client:
            resp = client.post(f"{base_url}/validate", json=payload)
    except Exception as exc:
        logger.error("Guardrails service is unreachable at %s: %s", base_url, exc)
        return _fail(validation_passed=True, error=str(exc), detail=None)

    if resp.status_code != 200:
        detail = resp.text[:500]
        logger.error("Guardrails service returned HTTP %s: %s", resp.status_code, detail)
        return _fail(
            validation_passed=True,
            error=f"HTTP {resp.status_code}",
            detail=detail,
        )

    try:
        body = resp.json()
        results = body.get("results") or {}
    except Exception as exc:
        logger.error("Guardrails service returned an unreadable body: %s", exc)
        return _fail(validation_passed=True, error=str(exc), detail=None)

    # Report a missing validator rather than silently treating it as passed.
    for guard in guards:
        results.setdefault(
            guard,
            {"validation_passed": True, "error": "validator missing from the response", "detail": None},
        )

    return {
        "results": results,
        "blocked": bool(body.get("blocked")),
        "blocked_by": body.get("blocked_by"),
        "chunks": body.get("chunks"),
        "text": body.get("text"),
        "skipped": bool(body.get("skipped")),
    }


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
    return run_guardrails_phase(text, guards, guardrails_url, timeout_s, settings)["results"]


def check_blocked(results: dict[str, dict[str, Any]]) -> tuple[bool, str | None]:
    """Check if any guard blocked the text."""
    for guard, res in results.items():
        if not res.get("validation_passed", True):
            return True, guard
    return False, None
