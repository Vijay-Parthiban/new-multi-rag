"""ASGI entrypoint for the guardrails service.

Endpoints
    GET  /health-check   liveness
    GET  /catalog        the validator catalog and the failure-action options
    POST /validate       run a validator list, built from the request, over one text

The service validates text that the chat pipeline already produced. It does not call an LLM
itself, except for the three ``local/*`` judges, which call the LiteLLM proxy.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from config import get_catalog, run_validators

logger = logging.getLogger(__name__)

app = FastAPI(title="guardrails-service", version="0.2.0")


class ValidatorSpec(BaseModel):
    """One validator and its parameters, as configured in the Guard Config page."""

    id: str
    params: dict[str, Any] = Field(default_factory=dict)
    on_fail: str = "noop"


class ValidateRequest(BaseModel):
    text: str
    phase: str = "both"
    validators: list[ValidatorSpec] = Field(default_factory=list)


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
    """Run every configured validator over the text.

    Results are keyed by validator id. ``blocked`` is true when any validator failed, and
    ``blocked_by`` names the first one. Each result carries ``validation_passed``, ``error``
    (a transport or configuration problem) and ``detail`` (the failure reason).
    """
    if not body.validators:
        raise HTTPException(status_code=422, detail="At least one validator is required")
    try:
        return run_validators(
            body.text,
            [v.model_dump() for v in body.validators],
            phase=body.phase,
        )
    except ValueError as exc:
        # A bad parameter value is the caller's problem, and the message is meant for the UI.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Validation failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
