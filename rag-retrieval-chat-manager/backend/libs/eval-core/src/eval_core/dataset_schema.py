from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

TURN_ROLES = frozenset({"user", "assistant"})


class GoldenTurnPayload(BaseModel):
    """One turn of a multi-turn row.

    The shape is the one both frameworks write: RAGAS's `MultiTurnSample.user_input` and
    DeepEval's `ConversationalGolden.turns` are both a list of role/content objects.
    """

    role: str
    content: str


class GoldenDatasetItemPayload(BaseModel):
    question: str
    ground_truth_answer: str | None = None
    expected_sources: list[Any] = Field(default_factory=list)
    # A conversation's user turns, in order. None on a single-turn row, which is every row
    # of every dataset written before this field existed.
    turns: list[GoldenTurnPayload] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("question must not be empty")
        return text

    @field_validator("turns")
    @classmethod
    def turns_are_well_formed(
        cls, value: list[GoldenTurnPayload] | None
    ) -> list[GoldenTurnPayload] | None:
        if value is None:
            return value
        for turn in value:
            if turn.role not in TURN_ROLES:
                raise ValueError("turn role must be user or assistant")
            if not turn.content.strip():
                raise ValueError("turn content must not be empty")
        if not any(turn.role == "user" for turn in value):
            raise ValueError("turns must contain at least one user turn")
        return value

    @model_validator(mode="after")
    def record_the_assistant_turns(self) -> GoldenDatasetItemPayload:
        """Keep the assistant turns as `expected_turns` in the metadata.

        The run replays the user turns only. These are the answers the conversation aimed
        at, and they are here so a stored row shows what it was aiming at.
        """
        expected = [
            {"content": turn.content} for turn in (self.turns or []) if turn.role == "assistant"
        ]
        if expected:
            self.metadata.setdefault("expected_turns", expected)
        return self


class GoldenDatasetPayload(BaseModel):
    name: str
    description: str | None = None
    # "single_turn" or "multi_turn". Derived from the items, never read from the file.
    kind: str = "single_turn"
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

    @model_validator(mode="before")
    @classmethod
    def accept_either_frameworks_field_names(cls, data: Any) -> Any:
        """Normalize the items before pydantic reads them.

        This is what makes the schema universal for a JSON body as well as a file: a
        caller that POSTs a RAGAS or DeepEval row gets the same treatment as one that
        uploads a CSV. Normalizing twice is harmless, and the upload path does exactly
        that, so the two doors agree.
        """
        if not isinstance(data, dict):
            return data
        items = data.get("items")
        if not isinstance(items, list):
            return data
        return {
            **data,
            "items": [
                _normalize_item(item) if isinstance(item, dict) else item for item in items
            ],
        }

    @model_validator(mode="after")
    def kind_from_items(self) -> GoldenDatasetPayload:
        """One dataset holds one kind of row.

        RAGAS and DeepEval both refuse a file that mixes a conversation with a lone
        question, so a mixed file is invalid everywhere rather than only here.
        """
        kinds = {"multi_turn" if item.turns else "single_turn" for item in self.items}
        if len(kinds) > 1:
            raise ValueError("a dataset cannot mix single-turn and multi-turn rows")
        self.kind = kinds.pop()
        return self


# Every column name this loader accepts, mapped to the field it fills. Both frameworks'
# own names are here so a file either one generates loads with no renaming. The canonical
# name wins when a file carries two spellings of the same field.
_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "question": ("question", "user_input", "input", "query"),
    "ground_truth_answer": (
        "ground_truth_answer",
        "reference",
        "expected_output",
        "expected_outcome",
    ),
    "reference_context": ("reference_context", "reference_contexts", "context"),
    "source_doc_id": ("source_doc_id", "expected_sources", "source"),
    "turns": ("turns", "conversation", "messages"),
}

# Keys that are never metadata: the row's own containers, and the two the model fills at
# run time. A dataset must not score a run against its own output.
_NON_METADATA_KEYS = frozenset(
    {"metadata", "additional_metadata", "custom_column_key_values", "response", "actual_output"}
)

# `response` is deliberately not an alias: for RAGAS it is the model's own answer, and
# reading it as the reference would score a run against itself. It still stands in for the
# project's older JSON papers, which carry no other answer field.


def _resolve_columns(names: Iterable[str]) -> dict[str, str | None]:
    """canonical field -> the name present in the source, or None.

    Header-order independent: a reordered file resolves the same way.
    """
    present = {str(name).strip().lower() for name in names if name}
    return {
        field: next((alias for alias in aliases if alias in present), None)
        for field, aliases in _COLUMN_ALIASES.items()
    }


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n\n".join(str(part).strip() for part in value if str(part).strip())
    return str(value).strip()


def _parse_turns(raw: Any) -> list[GoldenTurnPayload] | None:
    """The `turns` value, from a CSV cell or from a JSON/JSONL field."""
    if raw is None:
        return None
    if isinstance(raw, list):
        data = raw
    else:
        text = str(raw).strip()
        if not text:
            return None
        try:
            data = json.loads(text)
        except ValueError as exc:  # json.JSONDecodeError is a ValueError
            raise ValueError(
                "turns must be a JSON array of {role, content} objects"
            ) from exc
    if not isinstance(data, list) or any(
        not isinstance(entry, (dict, GoldenTurnPayload)) for entry in data
    ):
        raise ValueError("turns must be a JSON array of {role, content} objects")
    # A pass over an item that was already normalized hands back the models themselves, so
    # normalizing twice has to leave them alone.
    return [
        entry if isinstance(entry, GoldenTurnPayload) else GoldenTurnPayload.model_validate(entry)
        for entry in data
    ]


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


def _normalize_sources(value: Any) -> list[dict[str, Any]]:
    """The JSON shape of the sources field: a name, a list of names, or entry objects."""
    if value is None:
        return []
    if isinstance(value, (str, dict)):
        entry = _normalize_source_entry(value)
        return [entry] if entry else []
    if isinstance(value, list):
        return [entry for entry in (_normalize_source_entry(e) for e in value) if entry]
    return []


def _normalize_item(raw_item: dict[str, Any]) -> dict[str, Any]:
    keys = {str(key).strip().lower(): key for key in raw_item}
    resolved = {
        field: next((keys[alias] for alias in aliases if alias in keys), None)
        for field, aliases in _COLUMN_ALIASES.items()
    }

    def value_of(field: str) -> Any:
        key = resolved[field]
        return raw_item.get(key) if key else None

    answer = value_of("ground_truth_answer")
    if answer is None:
        # The older paper format names the answer `response`.
        answer = raw_item.get("response")

    question = value_of("question")
    turns = _parse_turns(value_of("turns"))
    if turns is None and isinstance(question, list):
        # RAGAS's multi-turn sample carries the conversation in `user_input`, so the list in
        # that field is the turns and the question is the last of them.
        turns = _parse_turns(question)
        question = None
    if turns:
        question = question or next(
            (turn.content for turn in reversed(turns) if turn.role == "user"), ""
        )

    metadata = dict(raw_item.get("metadata") or {})
    # A row's other scalar keys are metadata, the same way a CSV's other columns are.
    # Without this a JSON row that carries `question_type` loses its category block, and
    # a DeepEval golden loses `additional_metadata`.
    extra_metadata = raw_item.get("additional_metadata") or raw_item.get("custom_column_key_values")
    if isinstance(extra_metadata, dict):
        metadata.update(extra_metadata)
    consumed_aliases = {alias for aliases in _COLUMN_ALIASES.values() for alias in aliases}
    for key, value in raw_item.items():
        lowered = str(key).strip().lower()
        if lowered in consumed_aliases or lowered in _NON_METADATA_KEYS:
            continue
        if isinstance(value, (str, int, float, bool)):
            metadata.setdefault(lowered, value)
    context = _as_text(value_of("reference_context"))
    if context and not _has_no_reference(context):
        metadata[_CSV_REFERENCE_CONTEXT] = context

    return {
        "question": question,
        "ground_truth_answer": answer,
        "expected_sources": _normalize_sources(value_of("source_doc_id")),
        "turns": turns,
        "metadata": metadata,
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


def parse_golden_dataset_jsonl(raw: str | bytes, *, name: str | None = None) -> GoldenDatasetPayload:
    """Parse one JSON object per line, the shape RAGAS's `to_jsonl` writes.

    This is the only lossless interchange for a list-valued field: `from_csv` reads every
    cell as text, so `reference_contexts` comes back as a string and pydantic rejects it.
    """
    text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
    items: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"JSONL line {number} must be an object")
        items.append(_normalize_item(payload))

    dataset_name = (name or "").strip()
    if not dataset_name:
        raise ValueError("a name is required to import a CSV dataset")

    return GoldenDatasetPayload.model_validate(
        {"name": dataset_name, "description": None, "items": items}
    )


# The metadata key the gold passage of a row is kept under. Unchanged from the format the
# reference dataset and the docs already use.
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

      question              required, unless the row carries `turns`
      ground_truth_answer   the `reference` for RAGAS
      source_doc_id         page ids, `;`-separated, mapped to expected_sources
      reference_context     the gold context; a `NONE ...` marker counts as absent
      turns                 a conversation, as a JSON array of {role, content}

    A column may also use the name either framework gives it (`user_input`,
    `input`, `reference`, `expected_output`, `context`, `conversation`). Every other
    column (`id`, `question_type`, `expected_behavior`, `keypoints_covered`, `difficulty`,
    `notes`, ...) is kept in `metadata` and drives the custom metrics and the
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
    resolved = {
        field: next((lookup[alias] for alias in aliases if alias in lookup), None)
        for field, aliases in _COLUMN_ALIASES.items()
    }

    question_key = resolved["question"]
    if not question_key and not resolved["turns"]:
        raise ValueError(
            "CSV must have a 'question' column. Found: " + ", ".join(sorted(lookup))
        )

    answer_key = resolved["ground_truth_answer"]
    sources_key = resolved["source_doc_id"]
    reference_key = resolved["reference_context"]
    turns_key = resolved["turns"]

    reserved = set(resolved.values()) - {None}

    # A column that carries two names for the same field is fine while they agree, and is a
    # mistake as soon as they do not.
    shadowed: dict[str, list[str]] = {}
    for field, header in resolved.items():
        if not header:
            continue
        others = [
            lookup[alias]
            for alias in _COLUMN_ALIASES[field]
            if alias in lookup and lookup[alias] != header
        ]
        if others:
            shadowed[field] = others

    items: list[GoldenDatasetItemPayload] = []
    for row in reader:
        for field, others in shadowed.items():
            primary = str(row.get(resolved[field]) or "").strip()
            for other in others:
                value = str(row.get(other) or "").strip()
                if primary and value and value != primary:
                    raise ValueError(f"{resolved[field]} and {other} disagree; keep one")

        turns = _parse_turns(row.get(turns_key)) if turns_key else None
        question = str(row.get(question_key) or "").strip() if question_key else ""
        if turns:
            last_user = next(
                (turn.content for turn in reversed(turns) if turn.role == "user"), ""
            )
            if question and last_user and question != last_user:
                raise ValueError("question must match the last user turn of turns")
            question = question or last_user
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
                turns=turns,
                metadata=metadata,
            )
        )

    dataset_name = (name or "").strip()
    if not dataset_name:
        raise ValueError("a name is required to import a CSV dataset")

    return GoldenDatasetPayload.model_validate(
        {"name": dataset_name, "description": None, "items": items}
    )


# Every container the Dataset Fabric accepts. `.json` here means the wrapped object
# (`{"name", "items"}`); `.jsonl` is one item per line and is the only lossless form for a
# list-valued field.
UPLOAD_FORMATS = (".csv", ".json", ".jsonl", ".xlsx", ".parquet")


def parse_golden_dataset_dataframe(frame: Any, *, name: str) -> GoldenDatasetPayload:
    """A spreadsheet or Parquet table, through the CSV reader.

    Both are a CSV in another container, so the frame goes back to CSV text in memory
    and the CSV loader maps it. One reader means the column aliases and the row rules
    cannot drift between the three formats.

    ponytail: a list-valued cell is flattened to its repr, because `to_csv` does that.
    A dataset that carries a real list must arrive as JSONL.
    """
    if frame is None or len(frame) == 0:
        raise ValueError("the file holds no rows")
    # pandas makes an empty cell NaN and a number a float. The CSV reader works on text,
    # so normalize first; NaN becomes "", which the loader already treats as absent.
    text_frame = frame.astype("string").fillna("")
    return parse_golden_dataset_csv(text_frame.to_csv(index=False), name=name)


def parse_golden_dataset_file(
    raw: bytes | str, filename: str, *, name: str | None = None
) -> GoldenDatasetPayload:
    """Parse an upload by its file extension. The one entry point both upload routes use."""
    lower = (filename or "").strip().lower()
    suffix = next((fmt for fmt in UPLOAD_FORMATS if lower.endswith(fmt)), None)
    if suffix is None:
        raise ValueError(f"file must be one of {', '.join(UPLOAD_FORMATS)}")

    dataset_name = (name or "").strip() or Path(filename).stem
    if not dataset_name:
        raise ValueError("a name is required to import a dataset")

    if suffix in (".xlsx", ".parquet"):
        import pandas as pd

        buffer = io.BytesIO(raw.encode("utf-8") if isinstance(raw, str) else raw)
        frame = (
            pd.read_excel(buffer, dtype=str)
            if suffix == ".xlsx"
            else pd.read_parquet(buffer)
        )
        return parse_golden_dataset_dataframe(frame, name=dataset_name)
    if suffix == ".csv":
        return parse_golden_dataset_csv(raw, name=dataset_name)
    if suffix == ".jsonl":
        return parse_golden_dataset_jsonl(raw, name=dataset_name)

    payload = parse_golden_dataset_json(raw)
    if name and name.strip():
        payload = payload.model_copy(update={"name": name.strip()})
    return payload
