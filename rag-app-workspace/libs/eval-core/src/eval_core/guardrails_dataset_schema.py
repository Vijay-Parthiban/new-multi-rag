from __future__ import annotations

import json
from typing import Any
from pydantic import BaseModel, Field


class GuardrailsGoldenItem(BaseModel):
    id: str | None = None
    input_text: str
    expected_blocked: bool = False
    expected_guard: str | None = None
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
