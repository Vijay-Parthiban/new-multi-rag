from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
import httpx

from rag_shared.config import Settings, get_settings
from shared_contracts.knowledge import (
    KnowledgeProfileCreate,
    KnowledgeProfileRead,
    KnowledgeProfileUpdate,
    TestConnectionRequest,
    TestConnectionResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge-profiles", tags=["knowledge-profiles-proxy"])


def get_ingestion_url(settings: Settings = Depends(get_settings)) -> str:
    # Default to http://localhost:8007 if not specified
    base_url = getattr(settings, "ingestion_service_url", None) or "http://localhost:8007"
    return base_url.rstrip("/")


@router.get("", response_model=list[KnowledgeProfileRead])
async def list_knowledge_profiles(
    ingestion_url: str = Depends(get_ingestion_url),
) -> Any:
    """Proxy request to rag-ingestion-manager backend on port 8007."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(f"{ingestion_url}/api/knowledge-profiles")
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
        except httpx.RequestError as exc:
            logger.error("Failed to connect to ingestion manager: %s", exc)
            raise HTTPException(status_code=503, detail=f"Ingestion service unavailable: {str(exc)}")


@router.post("", response_model=KnowledgeProfileRead, status_code=201)
async def create_knowledge_profile(
    body: KnowledgeProfileCreate,
    ingestion_url: str = Depends(get_ingestion_url),
) -> Any:
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.post(f"{ingestion_url}/api/knowledge-profiles", json=body.model_dump(mode="json"))
            if resp.status_code not in (200, 201):
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail=f"Ingestion service unavailable: {str(exc)}")


@router.get("/{profile_id}", response_model=KnowledgeProfileRead)
async def get_knowledge_profile(
    profile_id: uuid.UUID,
    ingestion_url: str = Depends(get_ingestion_url),
) -> Any:
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(f"{ingestion_url}/api/knowledge-profiles/{profile_id}")
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail=f"Ingestion service unavailable: {str(exc)}")


@router.put("/{profile_id}", response_model=KnowledgeProfileRead)
async def update_knowledge_profile(
    profile_id: uuid.UUID,
    body: KnowledgeProfileUpdate,
    ingestion_url: str = Depends(get_ingestion_url),
) -> Any:
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.put(f"{ingestion_url}/api/knowledge-profiles/{profile_id}", json=body.model_dump(mode="json", exclude_unset=True))
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail=f"Ingestion service unavailable: {str(exc)}")


@router.delete("/{profile_id}")
async def delete_knowledge_profile(
    profile_id: uuid.UUID,
    ingestion_url: str = Depends(get_ingestion_url),
) -> Any:
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.delete(f"{ingestion_url}/api/knowledge-profiles/{profile_id}")
            if resp.status_code not in (200, 204):
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return Response(status_code=204)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail=f"Ingestion service unavailable: {str(exc)}")


@router.post("/{profile_id}/test-connection", response_model=TestConnectionResponse)
async def test_destination_connection(
    profile_id: uuid.UUID,
    body: TestConnectionRequest,
    ingestion_url: str = Depends(get_ingestion_url),
) -> Any:
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.post(f"{ingestion_url}/api/knowledge-profiles/{profile_id}/test-connection", json=body.model_dump(mode="json"))
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail=f"Ingestion service unavailable: {str(exc)}")


@router.post("/{profile_id}/sync")
async def trigger_fanout_sync(
    profile_id: uuid.UUID,
    ingestion_url: str = Depends(get_ingestion_url),
) -> Any:
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(f"{ingestion_url}/api/knowledge-profiles/{profile_id}/sync")
            if resp.status_code not in (200, 202):
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail=f"Ingestion service unavailable: {str(exc)}")
