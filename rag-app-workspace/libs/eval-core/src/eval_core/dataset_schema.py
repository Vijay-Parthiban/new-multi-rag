from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, field_validator


class GoldenDatasetItemPayload(BaseModel):
    question: str
    ground_truth_answer: str | None = None
    expected_sources: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("question must not be empty")
        return text


class GoldenDatasetPayload(BaseModel):
    name: str
    description: str | None = None
    items: list[GoldenDatasetItemPayload]

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("name must not be empty")
        return text

    @field_validator("items")
    @classmethod
    def items_not_empty(cls, value: list[GoldenDatasetItemPayload]) -> list[GoldenDatasetItemPayload]:
        if not value:
            raise ValueError("items must contain at least one entry")
        return value


def _normalize_item(raw_item: dict[str, Any]) -> dict[str, Any]:
    if "question" in raw_item:
        return raw_item
    source = raw_item.get("source", "")
    if isinstance(source, str):
        expected_sources = [source.strip()] if source.strip() else []
    elif isinstance(source, list):
        expected_sources = [str(s).strip() for s in source if str(s).strip()]
    else:
        expected_sources = []
    return {
        "question": raw_item["query"],
        "ground_truth_answer": raw_item.get("response"),
        "expected_sources": expected_sources,
        "metadata": raw_item.get("metadata") or {},
    }


def parse_golden_dataset_payload(data: dict[str, Any]) -> GoldenDatasetPayload:
    items = [_normalize_item(item) for item in data.get("items", [])]
    return GoldenDatasetPayload.model_validate({**data, "items": items})


def parse_golden_dataset_json(raw: str | bytes) -> GoldenDatasetPayload:
    if isinstance(raw, bytes):
        text = raw.decode("utf-8")
    else:
        text = raw
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("dataset JSON must be an object")
    return parse_golden_dataset_payload(payload)
