"""Prompt templates registry — list / update / reset temp overrides.

Packaged ``*.txt`` prompts are never modified. Edits are stored under the
system temp overrides directory and preferred by ``load_prompt`` until reset.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from generation_core.prompts import clear_prompt_cache as clear_gen_cache
from generation_core.prompts import load_packaged_prompt as load_gen_packaged
from generation_core.prompts import load_prompt as load_gen_prompt
from rag_core.prompts import clear_prompt_cache as clear_rag_cache
from rag_core.prompts import load_packaged_prompt as load_rag_packaged
from rag_core.prompts import load_prompt as load_rag_prompt
from rag_shared.prompt_overrides import (
    clear_all_overrides,
    clear_override,
    has_override,
    overrides_root,
    write_override,
)

router = APIRouter(prefix="/prompts", tags=["prompts"])

PackageName = Literal["generation_core", "rag_core"]


class PromptMeta(BaseModel):
    id: str
    filename: str
    package: PackageName
    label: str
    description: str


PROMPT_CATALOG: list[PromptMeta] = [
    PromptMeta(
        id="rag_system",
        filename="rag_system.txt",
        package="generation_core",
        label="RAG System",
        description="Main system prompt for text RAG answer generation.",
    ),
    PromptMeta(
        id="fusion_system",
        filename="fusion_system.txt",
        package="generation_core",
        label="Fusion System",
        description="Merges text and vision partial answers into a final reply.",
    ),
    PromptMeta(
        id="relevance_judge_system",
        filename="relevance_judge_system.txt",
        package="generation_core",
        label="Relevance Judge",
        description="Self-corrective loop: judges whether an answer is acceptable.",
    ),
    PromptMeta(
        id="query_rewrite_system",
        filename="query_rewrite_system.txt",
        package="generation_core",
        label="Query Rewrite",
        description="Self-corrective loop: rewrites the search query after a miss.",
    ),
    PromptMeta(
        id="vision_user",
        filename="vision_user.txt",
        package="generation_core",
        label="Vision User Template",
        description="User-message template for vision / image-based generation.",
    ),
    PromptMeta(
        id="llm_router_system",
        filename="llm_router_system.txt",
        package="rag_core",
        label="LLM Router",
        description="Classifies queries into greeting / simple RAG / CRAG routes.",
    ),
]

_BY_ID = {p.id: p for p in PROMPT_CATALOG}
_BY_FILENAME = {p.filename: p for p in PROMPT_CATALOG}


def _packaged(meta: PromptMeta) -> str:
    if meta.package == "generation_core":
        return load_gen_packaged(meta.filename)
    return load_rag_packaged(meta.filename)


def _active(meta: PromptMeta) -> str:
    if meta.package == "generation_core":
        return load_gen_prompt(meta.filename)
    return load_rag_prompt(meta.filename)


def _invalidate_caches() -> None:
    clear_gen_cache()
    clear_rag_cache()


def _get_meta(prompt_id: str) -> PromptMeta:
    meta = _BY_ID.get(prompt_id) or _BY_FILENAME.get(prompt_id)
    if meta is None:
        meta = _BY_ID.get(Path(prompt_id).stem)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Unknown prompt: {prompt_id}")
    return meta


class PromptSummary(BaseModel):
    id: str
    filename: str
    package: PackageName
    label: str
    description: str
    is_overridden: bool
    preview: str


class PromptDetail(BaseModel):
    id: str
    filename: str
    package: PackageName
    label: str
    description: str
    is_overridden: bool
    packaged_content: str
    active_content: str
    overrides_dir: str


class PromptListResponse(BaseModel):
    overrides_dir: str
    count: int
    items: list[PromptSummary]


class UpdatePromptRequest(BaseModel):
    content: str = Field(..., min_length=1)


class BulkUpdateItem(BaseModel):
    id: str
    content: str = Field(..., min_length=1)


class BulkUpdateRequest(BaseModel):
    items: list[BulkUpdateItem] = Field(..., min_length=1)


class ResetResponse(BaseModel):
    reset: list[str]
    overrides_dir: str


@router.get("", response_model=PromptListResponse)
def list_prompts() -> PromptListResponse:
    items: list[PromptSummary] = []
    for meta in PROMPT_CATALOG:
        active = _active(meta)
        preview = active if len(active) <= 160 else active[:157] + "..."
        items.append(
            PromptSummary(
                id=meta.id,
                filename=meta.filename,
                package=meta.package,
                label=meta.label,
                description=meta.description,
                is_overridden=has_override(meta.filename),
                preview=preview,
            )
        )
    return PromptListResponse(
        overrides_dir=str(overrides_root()),
        count=len(items),
        items=items,
    )


@router.put("", response_model=PromptListResponse)
def update_prompts_bulk(body: BulkUpdateRequest) -> PromptListResponse:
    for item in body.items:
        meta = _get_meta(item.id)
        write_override(meta.filename, item.content)
    _invalidate_caches()
    return list_prompts()


@router.post("/reset", response_model=ResetResponse)
def reset_all_prompts() -> ResetResponse:
    known = [m.filename for m in PROMPT_CATALOG]
    clear_all_overrides(known_ids=known)
    _invalidate_caches()
    return ResetResponse(reset=known, overrides_dir=str(overrides_root()))


@router.get("/{prompt_id}", response_model=PromptDetail)
def get_prompt(prompt_id: str) -> PromptDetail:
    meta = _get_meta(prompt_id)
    packaged = _packaged(meta)
    return PromptDetail(
        id=meta.id,
        filename=meta.filename,
        package=meta.package,
        label=meta.label,
        description=meta.description,
        is_overridden=has_override(meta.filename),
        packaged_content=packaged,
        active_content=_active(meta),
        overrides_dir=str(overrides_root()),
    )


@router.put("/{prompt_id}", response_model=PromptDetail)
def update_prompt(prompt_id: str, body: UpdatePromptRequest) -> PromptDetail:
    meta = _get_meta(prompt_id)
    write_override(meta.filename, body.content)
    _invalidate_caches()
    return get_prompt(meta.id)


@router.post("/{prompt_id}/reset", response_model=PromptDetail)
def reset_prompt(prompt_id: str) -> PromptDetail:
    meta = _get_meta(prompt_id)
    clear_override(meta.filename)
    _invalidate_caches()
    return get_prompt(meta.id)
