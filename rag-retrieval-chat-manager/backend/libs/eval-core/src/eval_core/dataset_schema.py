from __future__ import annotations

import csv
import io
import json
from typing import Any

from pydantic import BaseModel, Field, field_validator


class GoldenDatasetItemPayload(BaseModel):
    question: str
    ground_truth_answer: str | None = None
    expected_sources: list[Any] = Field(default_factory=list)
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


def _normalize_source_entry(entry: Any) -> dict[str, Any] | None:
    if isinstance(entry, str):
        name = entry.strip()
        return {"name": name} if name else None
    if isinstance(entry, dict):
        name = str(entry.get("name") or entry.get("source") or "").strip()
        if not name:
            return None
        out: dict[str, Any] = {"name": name}
        page = entry.get("page")
        if page is not None and page != "":
            try:
                out["page"] = int(page)
            except (TypeError, ValueError):
                pass
        return out
    return None


def _normalize_item(raw_item: dict[str, Any]) -> dict[str, Any]:
    if "question" in raw_item and "query" not in raw_item:
        # Legacy format — still normalize expected_sources to objects when possible.
        sources = raw_item.get("expected_sources") or []
        if sources and isinstance(sources[0], str):
            sources = [s for s in (_normalize_source_entry(s) for s in sources) if s]
        return {
            "question": raw_item["question"],
            "ground_truth_answer": raw_item.get("ground_truth_answer"),
            "expected_sources": sources,
            "metadata": raw_item.get("metadata") or {},
        }

    source = raw_item.get("source", [])
    if isinstance(source, str):
        expected_sources = [s for s in [_normalize_source_entry(source)] if s]
    elif isinstance(source, list):
        expected_sources = [s for s in (_normalize_source_entry(e) for e in source) if s]
    elif isinstance(source, dict):
        expected_sources = [s for s in [_normalize_source_entry(source)] if s]
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


# Columns the CSV format uses for the values that become real dataset fields. Everything
# else in the file is carried in `metadata`, which is JSONB on the item row, so a new
# column in the CSV needs no migration.
_CSV_QUESTION = "question"
_CSV_ANSWER = "ground_truth_answer"
_CSV_SOURCES = "source_doc_id"
_CSV_REFERENCE_CONTEXT = "reference_context"

# `reference_context` marks an unanswerable row with a sentence that says there is no
# reference. Storing it would make context precision measure against the words "NONE -
# there is no provision", so the marker is dropped and the row keeps no reference context.
_NO_REFERENCE_PREFIX = "none"

# A value in `source_doc_id` can be missing rather than pointing at a page.
_NO_SOURCE_VALUES = frozenset({"", "n/a", "na", "none", "null", "-"})


def _split_sources(raw: str) -> list[dict[str, str]]:
    """`CSR_p5;CSR_p6` becomes two expected sources. `N/A` becomes none."""
    out: list[dict[str, str]] = []
    for part in str(raw or "").replace(",", ";").split(";"):
        name = part.strip()
        if name.lower() in _NO_SOURCE_VALUES:
            continue
        out.append({"name": name})
    return out


def _has_no_reference(raw: str) -> bool:
    return str(raw or "").strip().lower().startswith(_NO_REFERENCE_PREFIX)


def parse_golden_dataset_csv(raw: str | bytes, *, name: str | None = None) -> GoldenDatasetPayload:
    """Parse a golden dataset CSV into the same payload the JSON path produces.

    Recognized columns, by header name and case-insensitively:

      question              required
      ground_truth_answer   the `reference` for RAGAS
      source_doc_id         page ids, `;`-separated, mapped to expected_sources
      reference_context     the gold context; a `NONE ...` marker counts as absent

    Every other column (`id`, `question_type`, `expected_behavior`, `keypoints_covered`,
    `difficulty`, `notes`, ...) is kept in `metadata` and drives the custom metrics and the
    per-category breakdown.
    """
    if isinstance(raw, bytes):
        text = raw.decode("utf-8-sig")
    else:
        text = raw

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")

    # Header lookup is case- and space-insensitive so `Question` and ` question ` both work.
    lookup = {h.strip().lower(): h for h in reader.fieldnames if h}
    question_key = lookup.get(_CSV_QUESTION)
    if not question_key:
        raise ValueError(
            "CSV must have a 'question' column. Found: " + ", ".join(sorted(lookup))
        )

    answer_key = lookup.get(_CSV_ANSWER)
    sources_key = lookup.get(_CSV_SOURCES)
    reference_key = lookup.get(_CSV_REFERENCE_CONTEXT)

    reserved = {question_key, answer_key, sources_key, reference_key} - {None}

    items: list[GoldenDatasetItemPayload] = []
    for row in reader:
        question = str(row.get(question_key) or "").strip()
        if not question:
            continue

        metadata: dict[str, Any] = {}
        for header, original in lookup.items():
            if original in reserved:
                continue
            value = row.get(original)
            if value is None:
                continue
            text_value = str(value).strip()
            if text_value:
                metadata[header] = text_value

        ground_truth = str(row.get(answer_key) or "").strip() if answer_key else ""
        reference_context = str(row.get(reference_key) or "").strip() if reference_key else ""
        if reference_context and not _has_no_reference(reference_context):
            metadata[_CSV_REFERENCE_CONTEXT] = reference_context

        items.append(
            GoldenDatasetItemPayload(
                question=question,
                ground_truth_answer=ground_truth or None,
                expected_sources=_split_sources(row.get(sources_key) or "") if sources_key else [],
                metadata=metadata,
            )
        )

    dataset_name = (name or "").strip()
    if not dataset_name:
        raise ValueError("a name is required to import a CSV dataset")

    return GoldenDatasetPayload.model_validate(
        {"name": dataset_name, "description": None, "items": items}
    )
