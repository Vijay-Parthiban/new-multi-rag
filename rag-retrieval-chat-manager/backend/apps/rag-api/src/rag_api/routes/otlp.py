"""OTLP/HTTP receiver for the OpenTelemetry Collector's `traces/feedback` pipeline.

The collector posts every chat turn span here as OTLP/JSON. Each one is stored in
`conversation_turns`, which is how the Dataset Feedback page knows which pipeline a turn
belonged to.
"""

from __future__ import annotations

import json
import logging
import zlib

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from rag_api.otlp_turns import parse_turn_spans
from rag_shared.config import Settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/otlp", tags=["otlp"])

MAX_BODY = 5 * 1024 * 1024


def _store(settings: Settings, records: list[dict]) -> None:
    from rag_db.repositories.conversation_turn_repository import ConversationTurnRepository
    from rag_db.services.database import get_session_factory

    with get_session_factory(settings)() as db:
        ConversationTurnRepository(db).insert_turns(records)
        db.commit()


@router.post("/v1/traces")
async def receive_traces(request: Request) -> dict:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise HTTPException(status_code=413, detail="Trace export is too large.")
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(status_code=415, detail="Set encoding: json on the collector exporter")
    if request.headers.get("content-encoding", "").lower() == "gzip":
        try:
            raw = zlib.decompressobj(31).decompress(raw, MAX_BODY + 1)
        except zlib.error as exc:
            raise HTTPException(status_code=400, detail="Invalid gzip body.") from exc
        if len(raw) > MAX_BODY:
            raise HTTPException(status_code=413, detail="Trace export is too large.")
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Body is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object.")

    records = parse_turn_spans(payload)
    if records:
        try:
            await run_in_threadpool(_store, request.app.state.settings, records)
        except SQLAlchemyError as exc:
            logger.warning("Could not store %d turn(s): %s", len(records), exc)
            # 503 makes the collector retry; a 400 would make it drop the batch.
            raise HTTPException(status_code=503, detail="Turn store unavailable.") from exc
    return {"partialSuccess": {}}
