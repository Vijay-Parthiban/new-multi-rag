"""Synthetic dataset generation with DeepEval Synthesizer.

The chunks are already in a Knowledge Product's Qdrant collection, so nothing is ingested
here: the run reads payloads, groups them by file, and asks the synthesiser for goldens
per group. A golden is converted to the row shape `golden_dataset_items` stores, so the
result is a real golden dataset that Offline Evaluation can select.

Multi-turn rows need one more step than the synthesiser gives. Its conversational goldens
carry a scenario and an expected outcome but no user turns, so a second model call writes
the dependent turns from the same context.

ponytail: `async_mode=False` and `max_concurrent=1` on the synthesiser. The LiteLLM proxy
in front of the model is the concurrency limit here, and one group at a time keeps the
progress counters truthful. Raise both if a run is slow and the proxy can take it.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any, Callable

# deepeval reads .env from the working directory at import time, which would overwrite the
# environment this service was started with. Set before the import.
os.environ.setdefault("DEEPEVAL_DISABLE_DOTENV", "1")

from deepeval.models.base_model import DeepEvalBaseLLM  # noqa: E402
from deepeval.synthesizer import Evolution, Synthesizer  # noqa: E402
from deepeval.synthesizer.config import (  # noqa: E402
    ConversationalStylingConfig,
    EvolutionConfig,
    FiltrationConfig,
    StylingConfig,
)
from openai import OpenAI  # noqa: E402
from pydantic import BaseModel, ValidationError  # noqa: E402
from qdrant_client.http import models as qmodels  # noqa: E402
from vector_core.qdrant_store import QdrantStore  # noqa: E402

# Re-exported: the tuples live in a module with no heavy imports, so rag-api can read them
# without loading deepeval into the API process.
from eval_core.synthesis_constants import EVOLUTION_NAMES, RAG_SAFE_EVOLUTIONS  # noqa: E402,F401

TURN_PROMPT = """You write a test conversation for a retrieval-augmented system.
Context:
{context}

Scenario: {scenario}
Expected outcome: {expected_outcome}

Write exactly {turns} user turns. Every turn is a question the context answers.
Each turn builds on the previous one, the way a follow-up does.
Write the factual answer to every turn, using only the context.

Reply with JSON only in this shape:
{{"turns": [{{"question": "...", "answer": "..."}}]}}"""


class SynthesisError(RuntimeError):
    """A version failure with a message the page can show as-is."""


@dataclass(frozen=True)
class ContextGroup:
    """The chunks of one file, in reading order: one synthesiser input."""

    file_key: str
    texts: list[str]


# How many model calls run at once. The synthesiser used to run them one at a time, so a
# seven-context dataset took minutes of wall time that the proxy could serve in parallel.
SYNTHESIS_CONCURRENCY = 4


class LiteLlmModel(DeepEvalBaseLLM):
    """The LiteLLM proxy as a deepeval model.

    `synthesizer` needs the same interface the judge metrics use, and the proxy speaks the
    OpenAI wire format, so the OpenAI client is the whole adapter.
    """

    def __init__(self, model: str, base_url: str, api_key: str) -> None:
        self._model = model
        self._base_url = base_url
        self._api_key = api_key
        # The SDK default is a 600 s timeout with two retries, so one stalled request
        # costs up to 30 minutes. A short budget turns a stall into a fast failure, and
        # the retry is kept at one because a second stall should fail the row, not the run.
        self._client = OpenAI(
            base_url=base_url, api_key=api_key, timeout=120.0, max_retries=1
        )

    def load_model(self) -> OpenAI:
        return self._client

    def _chat(self, prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        return response.choices[0].message.content or ""

    def generate(self, prompt: str, schema: type[BaseModel] | None = None) -> Any:
        """A plain reply, or a `schema` instance when deepeval asks for one.

        The synthesiser calls `generate(prompt, schema=...)` and reads fields off the
        reply. Returning a string there raised `'str' object has no attribute 'data'` on
        the first real run, so the schema path parses and validates here.
        """
        if schema is None:
            return self._chat(prompt)
        return self._chat_as_schema(prompt, schema)

    async def a_generate(self, prompt: str, schema: type[BaseModel] | None = None) -> Any:
        return await asyncio.to_thread(self.generate, prompt, schema)

    def _chat_as_schema(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        instruction = (
            "\n\nReply with JSON only, with no prose and no code fence. "
            "It must match this JSON schema:\n"
            + json.dumps(schema.model_json_schema())
        )
        working = prompt + instruction
        for attempt in range(2):
            try:
                return schema.model_validate_json(_json_block(self._chat(working)))
            except (json.JSONDecodeError, ValidationError) as exc:
                if attempt == 1:
                    raise
                working = (
                    f"{prompt}{instruction}\n\nYour previous reply was invalid: {exc}. "
                    "Reply with JSON only."
                )
        raise SynthesisError("The model returned no usable JSON.")

    def get_model_name(self) -> str:
        return self._model


def _text_of(chunk: dict) -> str:
    return str(chunk.get("text") or chunk.get("content") or "").strip()


def _int_of(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def build_contexts(chunks: list[dict], *, chunks_per_context: int) -> list[ContextGroup]:
    """Cut each file's chunks into consecutive runs of `chunks_per_context`.

    A parent record holds the whole file and would drown the real chunks, so it is
    skipped. The order is by file, then page: a group's texts then read in order.
    """
    seen: set[tuple[str, int, int]] = set()
    by_file: dict[str, list[tuple[int, int, str]]] = {}
    for chunk in chunks:
        if str(chunk.get("record_type") or "") == "parent":
            continue
        text = _text_of(chunk)
        if not text:
            continue
        file_key = str(chunk.get("file_key") or chunk.get("source_locator") or "unknown")
        page_index = _int_of(chunk.get("page_index"))
        chunk_index = _int_of(chunk.get("chunk_index"))
        key = (file_key, page_index, chunk_index)
        if key in seen:
            continue
        seen.add(key)
        by_file.setdefault(file_key, []).append((page_index, chunk_index, text))

    groups: list[ContextGroup] = []
    step = max(1, chunks_per_context)
    for file_key in sorted(by_file):
        ordered = [text for _, _, text in sorted(by_file[file_key])]
        for start in range(0, len(ordered), step):
            groups.append(ContextGroup(file_key=file_key, texts=ordered[start : start + step]))
    return groups


def chunks_for_product(
    settings: Any,
    *,
    collection: str,
    knowledge_product_id: str,
    limit: int = 5000,
) -> list[dict]:
    """The product's text chunks, as Qdrant payloads."""
    query_filter = qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key="knowledge_product_id", match=qmodels.MatchValue(value=knowledge_product_id)
            ),
            qmodels.FieldCondition(key="type", match=qmodels.MatchValue(value="text")),
        ]
    )
    store = QdrantStore(
        settings,
        collection=collection,
        url=settings.qdrant_kp_url or settings.qdrant_url,
    )
    return store.scroll_payloads(query_filter=query_filter, limit=limit)


def build_synthesizer(config: dict, model: LiteLlmModel) -> Synthesizer:
    names = [name for name in config.get("evolutions") or [] if name in EVOLUTION_NAMES]
    if not names:
        names = list(RAG_SAFE_EVOLUTIONS)
    share = 1.0 / len(names)

    filtration = config.get("filtration") or {}
    enabled = bool(filtration.get("enabled", True))
    # deepeval 4.3.2 reads `score` after a `for _ in range(max_quality_retries)` loop, so a
    # retry count of 0 raises UnboundLocalError in `_rewrite_scenarios`. One retry with a
    # threshold of 0 still never rewrites a scenario: the single score passes.
    retries = int(filtration.get("max_retries", 3)) if enabled else 1
    filtration_config = FiltrationConfig(
        critic_model=model,
        synthetic_input_quality_threshold=float(filtration.get("threshold", 0.5)) if enabled else 0.0,
        max_quality_retries=max(1, retries),
    )

    styling = {k: v for k, v in (config.get("styling") or {}).items() if v}
    conversational = {k: v for k, v in (config.get("conversational_styling") or {}).items() if v}

    return Synthesizer(
        model=model,
        # `async_mode` makes the synthesiser fan its calls out with a semaphore. Our
        # adapter offloads each blocking call to a thread, so this is real parallelism.
        async_mode=True,
        max_concurrent=SYNTHESIS_CONCURRENCY,
        evolution_config=EvolutionConfig(
            num_evolutions=int(config.get("num_evolutions", 1)),
            evolutions={Evolution[name.upper()]: share for name in names},
        ),
        filtration_config=filtration_config,
        styling_config=StylingConfig(**styling) if styling else None,
        conversational_styling_config=(
            ConversationalStylingConfig(**conversational) if conversational else None
        ),
    )


def _strip_fences(reply: str) -> str:
    return (
        reply.strip()
        .removeprefix("```json")
        .removeprefix("```")
        .removesuffix("```")
        .strip()
    )


def _json_block(reply: str) -> str:
    """The first JSON object in a reply, with a fence or a prose preamble removed.

    A reasoning model writes a sentence before its JSON even when the prompt asks it not
    to. `json.loads` refuses that, and the first `{` to the last `}` keeps the object.
    """
    text = _strip_fences(reply)
    start = text.find("{")
    end = text.rfind("}")
    return text[start : end + 1] if start >= 0 and end > start else text


def _valid_turns(payload: Any, turns: int) -> str | None:
    """`None` when the reply is usable, else the reason it is not."""
    if not isinstance(payload, dict):
        return "the reply is not a JSON object"
    items = payload.get("turns")
    if not isinstance(items, list):
        return "`turns` is not a list"
    if len(items) != turns:
        return f"expected {turns} turns, got {len(items)}"
    for item in items:
        if not isinstance(item, dict):
            return "a turn is not an object"
        if not str(item.get("question") or "").strip():
            return "a turn has no question"
        if not str(item.get("answer") or "").strip():
            return "a turn has no answer"
    return None


def _split_turns(
    model: LiteLlmModel,
    *,
    scenario: str,
    expected_outcome: str,
    context: list[str],
    turns: int,
) -> list[dict] | None:
    """Ask the model for `turns` dependent user turns and their answers.

    One retry, because the failure is a malformed reply and the second ask usually fixes
    it. After that the row is dropped and counted, rather than raising the whole run.
    """
    prompt = TURN_PROMPT.format(
        context="\n\n".join(context),
        scenario=scenario or "-",
        expected_outcome=expected_outcome or "-",
        turns=turns,
    )
    reason = "the reply was not JSON"
    for attempt in range(2):
        reply = model.generate(prompt)
        try:
            payload = json.loads(_strip_fences(reply))
        except json.JSONDecodeError as exc:
            reason = f"the reply is not JSON ({exc.msg})"
        else:
            reason = _valid_turns(payload, turns)
            if reason is None:
                return [
                    {
                        "question": str(item["question"]).strip(),
                        "answer": str(item["answer"]).strip(),
                    }
                    for item in payload["turns"]
                ]
        if attempt == 0:
            prompt = f"{prompt}\n\nYour previous reply was invalid: {reason}. Reply with JSON only."
    return None


def _base_metadata(
    golden: Any,
    group: ContextGroup,
    *,
    model: str,
    profile_id: str,
    version_id: str,
) -> dict:
    extra = getattr(golden, "additional_metadata", None) or {}
    return {
        "source": "synthetic",
        "model": model,
        "evolutions": extra.get("evolutions"),
        "context_quality": extra.get("context_quality"),
        "synthetic_input_quality": extra.get("synthetic_input_quality"),
        "source_contexts": list(group.texts),
        "synthetic_profile_id": profile_id,
        "synthetic_version_id": version_id,
    }


def _single_row(
    golden: Any, group: ContextGroup, *, model: str, profile_id: str, version_id: str
) -> dict:
    return {
        "question": golden.input,
        "ground_truth_answer": golden.expected_output,
        "expected_sources": [group.file_key],
        "turns": None,
        "metadata": _base_metadata(
            golden, group, model=model, profile_id=profile_id, version_id=version_id
        ),
    }


def _multi_row(
    golden: Any,
    group: ContextGroup,
    qa: list[dict],
    *,
    model: str,
    profile_id: str,
    version_id: str,
) -> dict:
    metadata = _base_metadata(
        golden, group, model=model, profile_id=profile_id, version_id=version_id
    )
    metadata["scenario"] = getattr(golden, "scenario", None)
    metadata["expected_outcome"] = getattr(golden, "expected_outcome", None)
    metadata["expected_turns"] = [{"content": item["answer"]} for item in qa]
    return {
        # The row's question is the last user turn: the evaluator replays `turns` in order
        # and grades the reply to that one.
        "question": qa[-1]["question"],
        "ground_truth_answer": qa[-1]["answer"],
        "expected_sources": [group.file_key],
        "turns": [{"role": "user", "content": item["question"]} for item in qa],
        "metadata": metadata,
    }


ProgressFn = Callable[[list[dict], int, int], None]


def synthesize_single(
    synth: Synthesizer,
    groups: list[ContextGroup],
    *,
    needed: int,
    per_context: int,
    model: str,
    profile_id: str,
    version_id: str,
    on_progress: ProgressFn,
) -> list[dict]:
    rows: list[dict] = []
    for index, group in enumerate(groups):
        goldens = synth.generate_goldens_from_contexts(
            contexts=[group.texts],
            source_files=[group.file_key],
            max_goldens_per_context=per_context,
            include_expected_output=True,
        )
        for golden in goldens:
            rows.append(
                _single_row(
                    golden, group, model=model, profile_id=profile_id, version_id=version_id
                )
            )
            if len(rows) >= needed:
                break
        on_progress(rows, len(groups), index)
        if len(rows) >= needed:
            break
    return rows


def synthesize_multi(
    synth: Synthesizer,
    groups: list[ContextGroup],
    *,
    needed: int,
    turns: int,
    per_context: int,
    model: LiteLlmModel,
    profile_id: str,
    version_id: str,
    on_progress: ProgressFn,
) -> tuple[list[dict], int]:
    rows: list[dict] = []
    skipped = 0
    for index, group in enumerate(groups):
        goldens = synth.generate_conversational_goldens_from_contexts(
            contexts=[group.texts],
            source_files=[group.file_key],
            max_goldens_per_context=per_context,
            include_expected_outcome=True,
        )
        for golden in goldens:
            qa = _split_turns(
                model,
                scenario=getattr(golden, "scenario", "") or "",
                expected_outcome=getattr(golden, "expected_outcome", "") or "",
                context=group.texts,
                turns=turns,
            )
            if qa is None:
                skipped += 1
                continue
            rows.append(
                _multi_row(
                    golden,
                    group,
                    qa,
                    model=model.get_model_name(),
                    profile_id=profile_id,
                    version_id=version_id,
                )
            )
            if len(rows) >= needed:
                break
        on_progress(rows, len(groups), index)
        if len(rows) >= needed:
            break
    return rows, skipped
