from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response

from rag_shared.config import Settings, get_settings
from shared_contracts.knowledge import (
    KnowledgeProductCreate,
    KnowledgeProductRead,
    KnowledgeProductUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge-products", tags=["knowledge-products-proxy"])


def get_ingestion_url(settings: Settings = Depends(get_settings)) -> str:
    # Default to http://localhost:8007 if not specified
    base_url = getattr(settings, "ingestion_service_url", None) or "http://localhost:8007"
    return base_url.rstrip("/")


@router.get("", response_model=list[KnowledgeProductRead])
async def list_knowledge_products(
    ingestion_url: str = Depends(get_ingestion_url),
) -> Any:
    """Proxy request to rag-ingestion-manager backend on port 8007."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(f"{ingestion_url}/api/knowledge-products")
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
        except httpx.RequestError as exc:
            logger.error("Failed to connect to ingestion manager: %s", exc)
            raise HTTPException(status_code=503, detail=f"Ingestion service unavailable: {str(exc)}")


@router.post("", response_model=KnowledgeProductRead, status_code=201)
async def create_knowledge_product(
    body: KnowledgeProductCreate,
    ingestion_url: str = Depends(get_ingestion_url),
) -> Any:
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.post(
                f"{ingestion_url}/api/knowledge-products", json=body.model_dump(mode="json")
            )
            if resp.status_code not in (200, 201):
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail=f"Ingestion service unavailable: {str(exc)}")


@router.get("/{product_id}", response_model=KnowledgeProductRead)
async def get_knowledge_product(
    product_id: uuid.UUID,
    ingestion_url: str = Depends(get_ingestion_url),
) -> Any:
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(f"{ingestion_url}/api/knowledge-products/{product_id}")
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail=f"Ingestion service unavailable: {str(exc)}")


@router.patch("/{product_id}", response_model=KnowledgeProductRead)
async def update_knowledge_product(
    product_id: uuid.UUID,
    body: KnowledgeProductUpdate,
    ingestion_url: str = Depends(get_ingestion_url),
) -> Any:
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.patch(
                f"{ingestion_url}/api/knowledge-products/{product_id}",
                json=body.model_dump(mode="json", exclude_unset=True),
            )
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail=f"Ingestion service unavailable: {str(exc)}")


@router.delete("/{product_id}")
async def delete_knowledge_product(
    product_id: uuid.UUID,
    ingestion_url: str = Depends(get_ingestion_url),
) -> Any:
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.delete(f"{ingestion_url}/api/knowledge-products/{product_id}")
            if resp.status_code not in (200, 204):
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return Response(status_code=204)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail=f"Ingestion service unavailable: {str(exc)}")


@router.post("/{product_id}/test-connection")
async def test_destination_connection(
    product_id: uuid.UUID,
    body: dict[str, Any],
    ingestion_url: str = Depends(get_ingestion_url),
) -> Any:
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.post(
                f"{ingestion_url}/api/knowledge-products/{product_id}/test-connection", json=body
            )
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail=f"Ingestion service unavailable: {str(exc)}")
