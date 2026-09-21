from __future__ import annotations

import json
from typing import Any
from pydantic import BaseModel, Field


class GuardrailsGoldenItem(BaseModel):
    """One labelled row. The field names match the stored columns and the bundled dataset."""

    text: str
    phase: str = "input"
    expected_blocked: bool = False
    expected_guard: str | None = None
    category: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GuardrailsGoldenDatasetPayload(BaseModel):
    name: str = "Guardrails Golden Dataset"
    description: str | None = None
    items: list[GuardrailsGoldenItem] = Field(default_factory=list)


def parse_guardrails_golden_json(content: bytes) -> GuardrailsGoldenDatasetPayload:
    data = json.loads(content.decode("utf-8"))
    if isinstance(data, list):
        items = [GuardrailsGoldenItem(**item) for item in data]
        return GuardrailsGoldenDatasetPayload(items=items)
    return GuardrailsGoldenDatasetPayload(**data)
