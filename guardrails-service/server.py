"""ASGI entrypoint that loads named guards from config.py at import time."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel
from guardrails.errors import ValidationError
from guardrails_api.app import create_app

app = create_app(None, "config.py")


class ParseRequest(BaseModel):
    llm_output: str
    metadata: dict[str, Any] | None = None


def _guards():
    # Imported after create_app() so hub validators are already loaded.
    import config as guard_config

    return {
        "ban-list": guard_config.ban_list,
        "pii-check": guard_config.pii_check,
        "toxic-language": guard_config.toxic_check,
    }


@app.post("/parse/{guard_name}")
def parse_guard(guard_name: str, body: ParseRequest) -> dict[str, Any]:
    """Validate existing text without going through the OpenAI-shaped /validate API.

    The stock ``POST /guards/{id}/validate`` path drops structured ``metadata``
    (OpenAI TypedDict collision) and treats missing ``llm_output`` as an LLM call.
    """
    guard = _guards().get(guard_name)
    if guard is None:
        raise HTTPException(status_code=404, detail=f"Unknown guard: {guard_name}")

    metadata = body.metadata or {}
    try:
        result = guard.parse(body.llm_output, metadata=metadata)
        passed = bool(getattr(result, "validation_passed", True))
        # Keep error=None on a real block so callers can tell it apart from
        # transport failures (those use a non-null error + passed=true).
        return {
            "validation_passed": passed,
            "error": None,
            "detail": None if passed else (getattr(result, "error", None) or "blocked"),
        }
    except ValidationError as exc:
        return {"validation_passed": False, "error": None, "detail": str(exc)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
