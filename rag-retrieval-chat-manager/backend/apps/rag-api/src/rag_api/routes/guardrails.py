"""
API routes for guardrails configuration CRUD and analytics.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from rag_db.repositories.guardrails_repository import GuardrailsRepository
from rag_db.services.database import get_session_factory
from rag_shared.config import Settings, get_settings
# The legacy guard-id and settings mapping lives in the shared client, so the chat path and
# the config API upgrade old rows the same way.
from rag_shared.guardrails_client import LEGACY_GUARD_IDS, upgrade_settings as _upgrade_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/guardrails", tags=["guardrails"])

# The validator catalog lives in the guardrails service, so there is exactly one definition
# of which validators exist and which parameters they take. Cache it briefly: the Guard
# Config page reads it on every load, and the service is a separate process.
_CATALOG_TTL_S = 60.0
_catalog_cache: dict[str, Any] = {"value": None, "at": 0.0}


def _fetch_catalog(settings: Settings) -> dict[str, Any]:
    """Return the service catalog, cached for a short time. Raises 503 when unavailable."""
    now = time.monotonic()
    cached = _catalog_cache["value"]
    if cached is not None and now - _catalog_cache["at"] < _CATALOG_TTL_S:
        return cached

    url = f"{settings.guardrails_url.rstrip('/')}/catalog"
    try:
        with httpx.Client(timeout=settings.guardrails_timeout_s) as client:
            resp = client.get(url)
            resp.raise_for_status()
            catalog = resp.json()
    except Exception as exc:
        logger.error("Could not read the guardrails catalog from %s: %s", url, exc)
        if cached is not None:
            # Serve a stale catalog rather than break the page on a service restart.
            return cached
        raise HTTPException(
            status_code=503,
            detail=f"Guardrails service is unavailable at {settings.guardrails_url}",
        ) from exc

    _catalog_cache["value"] = catalog
    _catalog_cache["at"] = now
    return catalog


def _catalog_guards(settings: Settings) -> list[dict[str, Any]]:
    return list(_fetch_catalog(settings).get("validators") or [])


def _catalog_on_fail(settings: Settings) -> list[dict[str, Any]]:
    return list(_fetch_catalog(settings).get("on_fail_options") or [])


def _guard_specs(settings: Settings) -> dict[str, dict[str, Any]]:
    return {g["id"]: g for g in _catalog_guards(settings)}


# ── Request / Response schemas ───────────────────────────────────────

class ConfigCreateRequest(BaseModel):
    name: str
    description: str | None = None
    guards: list[str]  # ids from the guardrails service catalog
    mode: str = "both"  # "input" | "output" | "both"
    settings: dict[str, Any] = Field(default_factory=dict)


class ConfigUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    guards: list[str] | None = None
    mode: str | None = None
    is_active: bool | None = None
    settings: dict[str, Any] | None = None


class ConfigResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    guards: list[str]
    settings: dict[str, Any] = Field(default_factory=dict)
    mode: str
    is_active: bool
    created_at: str | None = None
    updated_at: str | None = None


class ConfigListResponse(BaseModel):
    count: int
    items: list[ConfigResponse]


class TraceResponse(BaseModel):
    id: uuid.UUID
    # A trace written without a guardrails config has no config id. The column is
    # nullable, so the response must allow None.
    config_id: uuid.UUID | None = None
    config_name: str | None = None
    chat_message_id: uuid.UUID | None = None
    query: str
    response: str | None = None
    blocked: bool
    blocked_by_guard: str | None = None
    blocked_on: str | None = None
    guard_results: dict
    created_at: str | None = None


class TraceListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[TraceResponse]


class StatsResponse(BaseModel):
    total_requests: int
    blocked_requests: int
    passed_requests: int
    block_rate: float
    per_guard: dict[str, int]


class GuardItemOption(BaseModel):
    id: str
    label: str


class GuardParamSpec(BaseModel):
    name: str
    type: str
    label: str
    help: str = ""
    required: bool = False
    default: Any = None
    options: list[GuardItemOption] | None = None
    min: float | None = None
    max: float | None = None


class GuardOption(BaseModel):
    id: str
    label: str
    description: str
    category: str | None = None
    phase: str | None = None
    kind: str | None = None
    available: bool = True
    unavailable_reason: str | None = None
    params: list[GuardParamSpec] = []
    # Legacy fields, kept so an older client keeps working.
    items_key: str | None = None
    items_label: str | None = None
    allow_custom: bool = False
    options: list[GuardItemOption] = []


class OnFailOption(BaseModel):
    id: str
    label: str
    help: str
    fixes_text: bool = False


# ── Config CRUD endpoints ────────────────────────────────────────────


def _normalize_settings(raw: Any, guards: list[str], settings: Settings) -> dict[str, dict[str, Any]]:
    """Upgrade, strip to the selected guards, and check every parameter with the service."""
    nested = _upgrade_settings(raw, guards)

    # Only selected guards keep an entry, and every entry carries an explicit on_fail.
    cleaned: dict[str, dict[str, Any]] = {}
    for guard in guards:
        entry = nested.get(guard) or {}
        on_fail = str(entry.get("on_fail") or "noop")
        params = {k: v for k, v in entry.items() if k != "on_fail"}
        cleaned[guard] = {**params, "on_fail": on_fail}

    _assert_validators_ok(cleaned, settings)
    return cleaned


def _assert_validators_ok(normalized: dict[str, dict[str, Any]], settings: Settings) -> None:
    """Ask the service to check the parameters. Raises 422 with its message."""
    payload = {
        "validators": [
            {
                "id": guard,
                "params": {k: v for k, v in entry.items() if k != "on_fail"},
                "on_fail": entry.get("on_fail", "noop"),
            }
            for guard, entry in normalized.items()
        ]
    }
    url = f"{settings.guardrails_url.rstrip('/')}/validate-config"
    try:
        with httpx.Client(timeout=settings.guardrails_timeout_s) as client:
            resp = client.post(url, json=payload)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Guardrails service is unavailable at {settings.guardrails_url}",
        ) from exc

    if resp.status_code != 200:
        raise HTTPException(status_code=422, detail=f"Guardrails service rejected the config: {resp.text[:300]}")

    errors = (resp.json() or {}).get("errors") or []
    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))


@router.get("/guards", response_model=list[GuardOption])
def list_available_guards(settings: Settings = Depends(get_settings)) -> list[GuardOption]:
    """The validator catalog, read from the guardrails service.

    Each entry carries its parameter schema, so the Guard Config form is generated from the
    service rather than from a list kept here.
    """
    guards = []
    for spec in _catalog_guards(settings):
        # `options` used to live at the top level. Keep a copy for a client that reads it there.
        params = spec.get("params") or []
        primary = next((p for p in params if p.get("type") == "string_list"), None)
        guards.append(
            GuardOption(
                **{
                    **spec,
                    "items_key": primary["name"] if primary else None,
                    "items_label": primary["label"] if primary else None,
                    "allow_custom": not (primary or {}).get("options"),
                    "options": (primary or {}).get("options") or [],
                }
            )
        )
    return guards


@router.get("/on-fail-options", response_model=list[OnFailOption])
def list_on_fail_options(settings: Settings = Depends(get_settings)) -> list[OnFailOption]:
    """The actions a validator can take when the text fails."""
    return [OnFailOption(**o) for o in _catalog_on_fail(settings)]


@router.post("/configs", response_model=ConfigResponse, status_code=201)
def create_config(
    body: ConfigCreateRequest,
    settings: Settings = Depends(get_settings),
) -> ConfigResponse:
    if body.mode not in ("input", "output", "both"):
        raise HTTPException(status_code=422, detail="mode must be 'input', 'output', or 'both'")
    if not body.guards:
        raise HTTPException(status_code=422, detail="Select at least one guard")

    guards = [LEGACY_GUARD_IDS.get(g, g) for g in body.guards]
    known = _guard_specs(settings)
    for g in guards:
        if g not in known:
            raise HTTPException(status_code=422, detail=f"Unknown guard: {g}")

    normalized = _normalize_settings(body.settings, guards, settings)

    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = GuardrailsRepository(db)
        config = repo.create_config(
            name=body.name,
            guards=guards,
            mode=body.mode,
            description=body.description,
            settings=normalized,
        )
        db.commit()
        return _config_to_response(config)


@router.get("/configs", response_model=ConfigListResponse)
def list_configs(
    active_only: bool = False,
    settings: Settings = Depends(get_settings),
) -> ConfigListResponse:
    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = GuardrailsRepository(db)
        configs = repo.list_configs(active_only=active_only)
        items = [_config_to_response(c) for c in configs]
    return ConfigListResponse(count=len(items), items=items)


@router.get("/configs/{config_id}", response_model=ConfigResponse)
def get_config(
    config_id: uuid.UUID,
    settings: Settings = Depends(get_settings),
) -> ConfigResponse:
    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = GuardrailsRepository(db)
        config = repo.get_config(config_id)
        if not config:
            raise HTTPException(status_code=404, detail="Config not found")
        return _config_to_response(config)


@router.put("/configs/{config_id}", response_model=ConfigResponse)
def update_config(
    config_id: uuid.UUID,
    body: ConfigUpdateRequest,
    settings: Settings = Depends(get_settings),
) -> ConfigResponse:
    updates = body.model_dump(exclude_unset=True)
    if "mode" in updates and updates["mode"] not in ("input", "output", "both"):
        raise HTTPException(status_code=422, detail="mode must be 'input', 'output', or 'both'")
    if "guards" in updates:
        if not updates["guards"]:
            raise HTTPException(status_code=422, detail="Select at least one guard")
        updates["guards"] = [LEGACY_GUARD_IDS.get(g, g) for g in updates["guards"]]
        known = _guard_specs(settings)
        for g in updates["guards"]:
            if g not in known:
                raise HTTPException(status_code=422, detail=f"Unknown guard: {g}")

    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = GuardrailsRepository(db)
        existing = repo.get_config(config_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Config not found")

        next_guards = updates.get("guards") or [
            LEGACY_GUARD_IDS.get(g, g) for g in (existing.guards or [])
        ]
        if "settings" in updates or "guards" in updates:
            raw_settings = updates.get("settings", existing.settings or {})
            updates["settings"] = _normalize_settings(raw_settings, next_guards, settings)
            updates["guards"] = next_guards

        config = repo.update_config(config_id, **updates)
        if not config:
            raise HTTPException(status_code=404, detail="Config not found")
        db.commit()
        return _config_to_response(config)


@router.delete("/configs/{config_id}")
def delete_config(
    config_id: uuid.UUID,
    settings: Settings = Depends(get_settings),
) -> Response:
    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = GuardrailsRepository(db)
        if not repo.delete_config(config_id):
            raise HTTPException(status_code=404, detail="Config not found")
        db.commit()
    return Response(status_code=204)

# ── Analytics endpoints ──────────────────────────────────────────────

@router.get("/traces", response_model=TraceListResponse)
def list_traces(
    guard: str | None = None,
    blocked: bool | None = None,
    config_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
    settings: Settings = Depends(get_settings),
) -> TraceListResponse:
    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = GuardrailsRepository(db)
        traces, total = repo.list_traces(
            guard=guard, blocked=blocked, config_id=config_id,
            limit=limit, offset=offset,
        )
        # Eagerly load config names
        config_cache: dict[uuid.UUID | None, str] = {}
        items = []
        for t in traces:
            if t.config_id not in config_cache:
                if t.config_id is None:
                    # The turn ran with no guardrails config, so no config was deleted.
                    config_cache[None] = "No config"
                else:
                    cfg = repo.get_config(t.config_id)
                    config_cache[t.config_id] = cfg.name if cfg else "Deleted"
            items.append(_trace_to_response(t, config_cache[t.config_id]))

    return TraceListResponse(total=total, limit=limit, offset=offset, items=items)


@router.get("/stats", response_model=StatsResponse)
def get_stats(
    settings: Settings = Depends(get_settings),
) -> StatsResponse:
    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = GuardrailsRepository(db)
        stats = repo.get_stats()
    return StatsResponse(**stats)


# ── Helpers ──────────────────────────────────────────────────────────

def _config_to_response(config) -> ConfigResponse:
    # Rows written before the catalog existed hold the old flat settings and the old
    # `pii_check` id. Upgrade on read so the UI only ever sees the current shape.
    guards = [LEGACY_GUARD_IDS.get(g, g) for g in (config.guards or [])]
    return ConfigResponse(
        id=config.id,
        name=config.name,
        description=config.description,
        guards=guards,
        settings=_upgrade_settings(config.settings, guards),
        mode=config.mode,
        is_active=config.is_active,
        created_at=config.created_at.isoformat() if config.created_at else None,
        updated_at=config.updated_at.isoformat() if config.updated_at else None,
    )


def _trace_to_response(trace, config_name: str | None = None) -> TraceResponse:
    return TraceResponse(
        id=trace.id,
        config_id=trace.config_id,
        config_name=config_name,
        chat_message_id=trace.chat_message_id,
        query=trace.query,
        response=trace.response,
        blocked=trace.blocked,
        blocked_by_guard=trace.blocked_by_guard,
        blocked_on=trace.blocked_on,
        guard_results=trace.guard_results,
        created_at=trace.created_at.isoformat() if trace.created_at else None,
    )
