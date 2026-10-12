"""ASGI entrypoint for the guardrails service.

Endpoints
    GET  /health-check   liveness
    GET  /catalog        the validator catalog and the failure-action options
    POST /validate-config  check that a guard config can be built, without running it
    POST /validate       run one phase of a guard config over the text

The service checks text that the chat pipeline already produced. It generates no answer. The
rail engine decides which rails run in a phase; the ``local/*`` judges and the LLM-backed
rails reach the LiteLLM proxy.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from config import get_catalog
from nemo import EngineUnavailable, run_check

logger = logging.getLogger(__name__)

app = FastAPI(title="guardrails-service", version="0.3.0")


class ValidatorSpec(BaseModel):
    """One validator and its parameters, as configured in the Guard Config page."""

    id: str
    params: dict[str, Any] = Field(default_factory=dict)
    on_fail: str = "noop"


class ValidateRequest(BaseModel):
    text: str
    phase: str = "both"
    validators: list[ValidatorSpec] = Field(default_factory=list)
    # The output phase checks the answer against the passages it was built from, so the fact
    # check rail needs both. A caller that has no passages leaves `chunks` empty.
    query: str | None = None
    answer: str | None = None
    chunks: list[str] = Field(default_factory=list)


class ValidateConfigRequest(BaseModel):
    validators: list[ValidatorSpec] = Field(default_factory=list)


@app.get("/health-check")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/catalog")
def catalog() -> dict[str, Any]:
    """The validator catalog. The Guard Config page is generated from this."""
    return get_catalog()


@app.post("/validate-config")
def validate_config(body: ValidateConfigRequest) -> dict[str, Any]:
    """Check that a validator list and its parameters can be built. Runs nothing.

    The config API calls this before it saves, so a bad parameter is rejected at save time
    instead of surfacing later on a chat turn.
    """
    from config import validate_validators

    errors = validate_validators([v.model_dump() for v in body.validators])
    return {"valid": not errors, "errors": errors}


@app.post("/validate")
def validate(body: ValidateRequest) -> dict[str, Any]:
    """Run one phase of a guard config over the text.

    Results are keyed by catalog id. ``blocked`` is true when a rail or a validator failed, and
    ``blocked_by`` names the first one. Each result carries ``validation_passed``, ``error``
    (a transport or configuration problem), ``detail`` (the failure reason) and ``ms`` (what
    the rail cost, on the engine path). ``chunks`` comes back only for the retrieval phase:
    the passages, with any masked text in the same places. ``text`` comes back only for an
    output phase whose repair rail masked the answer.
    """
    if not body.validators:
        raise HTTPException(status_code=422, detail="At least one validator is required")
    validators = [v.model_dump() for v in body.validators]
    try:
        return run_check(
            body.text,
            validators,
            phase=body.phase,
            query=body.query,
            answer=body.answer,
            chunks=body.chunks,
        )
    except ValueError as exc:
        # A bad parameter value is the caller's problem, and the message is meant for the UI.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EngineUnavailable as exc:
        # The rail list needs an engine that this installation cannot build. The client fails
        # open on a non-200 answer, so the turn still runs.
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Validation failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
