"""API routes for prompt template CRUD.

A prompt template is the system message a pipeline attaches. Retrieve it by id
in the assistant path; see ``rag_api/routes/assistants.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from rag_db.models.prompt import PromptTemplate
from rag_db.repositories.prompt_repository import PromptRepository
from rag_db.services.database import get_session_factory
from rag_shared.config import Settings, get_settings

router = APIRouter(prefix="/prompt-templates", tags=["prompt-templates"])


class PromptTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    content: str = Field(min_length=1)


class PromptTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    content: str | None = Field(default=None, min_length=1)


class PromptTemplateResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    content: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PromptTemplateListResponse(BaseModel):
    count: int
    items: list[PromptTemplateResponse]


def _to_response(template: PromptTemplate) -> PromptTemplateResponse:
    return PromptTemplateResponse(
        id=template.id,
        name=template.name,
        description=template.description,
        content=template.content,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


def _name_taken(name: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "PROMPT_TEMPLATE_NAME_TAKEN",
            "message": f"A prompt template named '{name}' already exists.",
        },
    )


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "PROMPT_TEMPLATE_NOT_FOUND", "message": "Prompt template not found."},
    )


@router.post("", response_model=PromptTemplateResponse, status_code=201)
def create_prompt_template(
    body: PromptTemplateCreate,
    settings: Settings = Depends(get_settings),
) -> PromptTemplateResponse:
    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = PromptRepository(db)
        if repo.get_by_name(body.name):
            raise _name_taken(body.name)
        template = repo.create(name=body.name, content=body.content, description=body.description)
        db.commit()
        return _to_response(template)


@router.get("", response_model=PromptTemplateListResponse)
def list_prompt_templates(
    settings: Settings = Depends(get_settings),
) -> PromptTemplateListResponse:
    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = PromptRepository(db)
        items = [_to_response(t) for t in repo.list()]
    return PromptTemplateListResponse(count=len(items), items=items)


@router.get("/{template_id}", response_model=PromptTemplateResponse)
def get_prompt_template(
    template_id: uuid.UUID,
    settings: Settings = Depends(get_settings),
) -> PromptTemplateResponse:
    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = PromptRepository(db)
        template = repo.get(template_id)
        if not template:
            raise _not_found()
        return _to_response(template)


@router.put("/{template_id}", response_model=PromptTemplateResponse)
def update_prompt_template(
    template_id: uuid.UUID,
    body: PromptTemplateUpdate,
    settings: Settings = Depends(get_settings),
) -> PromptTemplateResponse:
    updates = body.model_dump(exclude_unset=True)
    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = PromptRepository(db)
        if not repo.get(template_id):
            raise _not_found()
        new_name = updates.get("name")
        if new_name:
            clash = repo.get_by_name(new_name)
            if clash and clash.id != template_id:
                raise _name_taken(new_name)
        template = repo.update(template_id, **updates)
        db.commit()
        return _to_response(template)


@router.delete("/{template_id}")
def delete_prompt_template(
    template_id: uuid.UUID,
    settings: Settings = Depends(get_settings),
) -> Response:
    session_factory = get_session_factory(settings)
    with session_factory() as db:
        repo = PromptRepository(db)
        if not repo.delete(template_id):
            raise _not_found()
        db.commit()
    return Response(status_code=204)
