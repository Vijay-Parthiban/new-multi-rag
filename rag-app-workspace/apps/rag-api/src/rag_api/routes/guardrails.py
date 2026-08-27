"""
API routes for guardrails configuration CRUD and analytics.
"""

from __future__ import annotations

import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from rag_db.repositories.guardrails_repository import GuardrailsRepository
from rag_db.services.database import get_session_factory
from rag_shared.config import Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/guardrails", tags=["guardrails"])

# Presidio entity types supported by DetectPII (pii + spi maps).
# https://microsoft.github.io/presidio/supported_entities/
PII_ENTITY_OPTIONS = [
    {"id": "EMAIL_ADDRESS", "label": "Email Address"},
    {"id": "PHONE_NUMBER", "label": "Phone Number"},
    {"id": "CREDIT_CARD", "label": "Credit Card"},
    {"id": "US_SSN", "label": "US SSN"},
    {"id": "IP_ADDRESS", "label": "IP Address"},
    {"id": "PERSON", "label": "Person Name"},
    {"id": "LOCATION", "label": "Location"},
    {"id": "DATE_TIME", "label": "Date / Time"},
    {"id": "URL", "label": "URL"},
    {"id": "DOMAIN_NAME", "label": "Domain Name"},
    {"id": "US_PASSPORT", "label": "US Passport"},
    {"id": "US_DRIVER_LICENSE", "label": "US Driver License"},
    {"id": "US_BANK_NUMBER", "label": "US Bank Number"},
    {"id": "US_ITIN", "label": "US ITIN"},
    {"id": "IBAN_CODE", "label": "IBAN Code"},
    {"id": "CRYPTO", "label": "Crypto Wallet"},
    {"id": "MEDICAL_LICENSE", "label": "Medical License"},
    {"id": "NRP", "label": "Nationality / Religion / Political group"},
]

# Available guard choices shown in the UI
AVAILABLE_GUARDS = [
    {
        "id": "ban_list",
        "label": "Ban List",
        "description": "Block specific keywords (case-insensitive)",
        "items_key": "banned_words",
        "items_label": "Keywords",
        "allow_custom": True,
        "options": [],
    },
    {
        "id": "pii_check",
        "label": "PII Detection",
        "description": "Detect personal identifiable information",
        "items_key": "pii_entities",
        "items_label": "PII types",
        "allow_custom": False,
        "options": PII_ENTITY_OPTIONS,
    },
    {
        "id": "toxic_language",
        "label": "Toxic Language",
        "description": "Flag toxic or harmful language",
        "items_key": None,
        "items_label": None,
        "allow_custom": False,
        "options": [],
    },
]

_VALID_GUARD_IDS = {g["id"] for g in AVAILABLE_GUARDS}
_VALID_PII_IDS = {o["id"] for o in PII_ENTITY_OPTIONS}


# ── Request / Response schemas ───────────────────────────────────────

class GuardSettings(BaseModel):
    banned_words: list[str] = []
    pii_entities: list[str] = []


class ConfigCreateRequest(BaseModel):
    name: str
    description: str | None = None
    guards: list[str]  # subset of ["ban_list", "pii_check", "toxic_language"]
    mode: str = "both"  # "input" | "output" | "both"
    settings: GuardSettings = Field(default_factory=GuardSettings)


class ConfigUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    guards: list[str] | None = None
    mode: str | None = None
    is_active: bool | None = None
    settings: GuardSettings | None = None


class ConfigResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    guards: list[str]
    settings: GuardSettings = Field(default_factory=GuardSettings)
    mode: str
    is_active: bool
    created_at: str | None = None
    updated_at: str | None = None


class ConfigListResponse(BaseModel):
    count: int
    items: list[ConfigResponse]


class TraceResponse(BaseModel):
    id: uuid.UUID
    config_id: uuid.UUID
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


class GuardOption(BaseModel):
    id: str
    label: str
    description: str
    items_key: str | None = None
    items_label: str | None = None
    allow_custom: bool = False
    options: list[GuardItemOption] = []


# ── Config CRUD endpoints ────────────────────────────────────────────

def _normalize_settings(raw: GuardSettings | dict | None, guards: list[str]) -> dict:
    """Validate and strip list settings for guards that are not selected."""
    if raw is None:
        data = GuardSettings()
    elif isinstance(raw, GuardSettings):
        data = raw
    else:
        data = GuardSettings.model_validate(raw)

    banned = [w.strip().lower() for w in data.banned_words if isinstance(w, str) and w.strip()]
    # De-dupe case-insensitively while preserving order
    seen: set[str] = set()
    banned_unique: list[str] = []
    for w in banned:
        if w not in seen:
            seen.add(w)
            banned_unique.append(w)

    pii: list[str] = []
    seen_pii: set[str] = set()
    for ent in data.pii_entities:
        if ent not in _VALID_PII_IDS:
            raise HTTPException(status_code=422, detail=f"Unknown PII entity: {ent}")
        if ent not in seen_pii:
            seen_pii.add(ent)
            pii.append(ent)

    if "ban_list" in guards and not banned_unique:
        raise HTTPException(
            status_code=422,
            detail="Ban List is enabled — add at least one keyword",
        )
    if "pii_check" in guards and not pii:
        raise HTTPException(
            status_code=422,
            detail="PII Detection is enabled — select at least one PII type",
        )

    return {
        "banned_words": banned_unique if "ban_list" in guards else [],
        "pii_entities": pii if "pii_check" in guards else [],
    }


@router.get("/guards", response_model=list[GuardOption])
def list_available_guards() -> list[GuardOption]:
    """Return the list of available guard types for building configs."""
    return [GuardOption(**g) for g in AVAILABLE_GUARDS]


@router.post("/configs", response_model=ConfigResponse, status_code=201)
def create_config(
    body: ConfigCreateRequest,
    settings: Settings = Depends(get_settings),
) -> ConfigResponse:
    if body.mode not in ("input", "output", "both"):
        raise HTTPException(status_code=422, detail="mode must be 'input', 'output', or 'both'")
    for g in body.guards:
        if g not in _VALID_GUARD_IDS:
            raise HTTPException(status_code=422, detail=f"Unknown guard: {g}")
    if not body.guards:
        raise HTTPException(status_code=422, detail="Select at least one guard")

    normalized = _normalize_settings(body.settings, body.guards)

    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = GuardrailsRepository(db)
        config = repo.create_config(
            name=body.name,
            guards=body.guards,
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
        for g in updates["guards"]:
            if g not in _VALID_GUARD_IDS:
                raise HTTPException(status_code=422, detail=f"Unknown guard: {g}")
        if not updates["guards"]:
            raise HTTPException(status_code=422, detail="Select at least one guard")

    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = GuardrailsRepository(db)
        existing = repo.get_config(config_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Config not found")

        next_guards = updates.get("guards", existing.guards)
        if "settings" in updates or "guards" in updates:
            raw_settings = updates.get("settings", existing.settings or {})
            updates["settings"] = _normalize_settings(raw_settings, next_guards)

        config = repo.update_config(config_id, **updates)
        if not config:
            raise HTTPException(status_code=404, detail="Config not found")
        db.commit()
        return _config_to_response(config)


@router.delete("/configs/{config_id}", status_code=204)
def delete_config(
    config_id: uuid.UUID,
    settings: Settings = Depends(get_settings),
) -> None:
    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = GuardrailsRepository(db)
        if not repo.delete_config(config_id):
            raise HTTPException(status_code=404, detail="Config not found")
        db.commit()


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
        config_cache: dict[uuid.UUID, str] = {}
        items = []
        for t in traces:
            if t.config_id not in config_cache:
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
    raw = config.settings or {}
    return ConfigResponse(
        id=config.id,
        name=config.name,
        description=config.description,
        guards=config.guards,
        settings=GuardSettings(
            banned_words=list(raw.get("banned_words") or []),
            pii_entities=list(raw.get("pii_entities") or []),
        ),
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
