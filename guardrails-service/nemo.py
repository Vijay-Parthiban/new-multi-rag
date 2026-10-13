"""NeMo Guardrails, the rail engine of this service.

One guard config becomes one NeMo configuration, built in memory from the same catalog entry
list the chat route already sends. Nothing is written to disk: the config lives in Postgres
and the Guard Config page is generated from the same catalog, so the engine reads the config
from the request instead of from a folder.

The engine checks, it does not generate. The application generates the answer itself, then
asks the engine whether the user message and that answer may pass. Colang 1.0 is the flow
language: the Guardrails Library is not fully usable from Colang 2.0 yet.

Phases
    input      before retrieval: self check, jailbreak heuristics, the configured validators
    retrieval  on the passages that will reach the model: PII detect or mask
    output     on the finished answer: self check, fact check, the configured validators

A config that names no rail takes the old path in ``config.run_validators`` and never builds
an engine, so an existing config behaves exactly as it did before this module existed.
"""

from __future__ import annotations

import json
import logging
import re
import time
from functools import lru_cache
from typing import Any, Callable

from config import (
    CATALOG_BY_ID,
    FACTS_RUBRIC,
    INPUT_POLICY_LINES,
    JAILBREAK_RUBRIC,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    NEMO_IMPORT_ERROR,
    OUTPUT_POLICY_LINES,
    RAIL_SPECS,
    SCOPE_RUBRIC,
    _ask_judge,
    run_single_validator,
    run_validators,
)

logger = logging.getLogger(__name__)

try:
    from nemoguardrails import LLMRails, RailsConfig
except Exception as exc:  # noqa: BLE001 - config.NEMO_IMPORT_ERROR carries the same reason
    LLMRails = None  # type: ignore[assignment,misc]
    RailsConfig = None  # type: ignore[assignment,misc]
    logger.warning("NeMo Guardrails is not importable: %s", exc)

# Rail id -> the library flow that implements it. These flows run, and the config supplies the
# prompts they render.
RAIL_FLOWS: dict[str, str] = {
    "self_check_input": "self check input",
    "self_check_output": "self check output",
    "pii_retrieval": "detect sensitive data on input",
}

# Rails that run as a flow of this service's own making, with a judge action behind it. The
# engine's fact-check flow never runs in a check-only call, and its jailbreak rail needs either a
# model server or torch with gpt2-large, neither of which this deployment runs. Both judge with
# the same LiteLLM proxy as the other LLM guards.
RAIL_ACTIONS: dict[str, str] = {
    "self_check_facts": "check_guard_self_check_facts",
    "jailbreak_heuristics": "check_guard_jailbreak_heuristics",
    "template_scope": "check_guard_template_scope",
}

_RAIL_RUBRICS: dict[str, str] = {
    "jailbreak_heuristics": JAILBREAK_RUBRIC,
    "self_check_facts": FACTS_RUBRIC,
    "template_scope": SCOPE_RUBRIC,
}

# Above this score a rail blocks.
_RAIL_THRESHOLD = 0.5

# Rail id -> the prompt task the policy parameter replaces, when the rail has one.
RAIL_PROMPTS: dict[str, str] = {
    "self_check_input": "self_check_input",
    "self_check_output": "self_check_output",
}

# This engine version ships no prompt for the self-check tasks, so the config supplies both. The
# variables and the "Yes or No" question are the ones the rail actions render and parse, so a
# prompt must keep them.

def _prompt_body(task: str, policy: str) -> str:
    """The prompt for one self-check task, with the config's policy appended."""
    if task == "self_check_input":
        headline = (
            "Your task is to check if the user message below complies with the company policy "
            "for talking with the company bot."
        )
        heading = "Company policy for the user messages:"
        bullets = INPUT_POLICY_LINES
        subject = 'User message: "{{ user_input }}"'
        question = "Question: Should the user message be blocked (Yes or No)?"
    else:
        headline = "Your task is to check if the bot message below complies with the company policy."
        heading = "Company policy for the bot:"
        bullets = OUTPUT_POLICY_LINES
        subject = 'Bot message: "{{ bot_response }}"'
        question = "Question: Should the message be blocked (Yes or No)?"

    body = [headline, "", heading]
    body.extend(f"- {line}" for line in bullets)
    if policy:
        body.extend(["", "Additional policy:", policy])
    body.extend(["", subject, "", question, "Answer:"])
    return "\n".join(body)


# Model types the engine resolves per rail. A rail without its own entry uses `main`.
_RAIL_MODEL_TYPES: dict[str, str] = {
    "self_check_input": "self_check_input",
    "self_check_output": "self_check_output",
    "self_check_facts": "self_check_facts",
}

RAIL_IDS = {spec["id"] for spec in RAIL_SPECS}
# Rail id -> its catalog phase.
RAIL_PHASES = {spec["id"]: spec["phase"] for spec in RAIL_SPECS}

_FACTS_SKIPPED = "skipped: no retrieval context"
_NOT_RUN = "not run: an earlier rail blocked the turn"
_NOT_IN_PHASE = "not run: this guard has no place in this phase"


class EngineUnavailable(RuntimeError):
    """The engine cannot be built. The caller answers 500 and the client fails open."""


# ── Config generation ────────────────────────────────────────────────


def _model_block(model: str, **extra: Any) -> dict[str, Any]:
    return {
        "engine": "openai",
        "model": model,
        "parameters": {"base_url": LLM_BASE_URL, "api_key": LLM_API_KEY, **extra},
    }


def _rails_of(rails: list[dict[str, Any]], phase: str) -> list[dict[str, Any]]:
    """The rail entries of one phase, in the order the caller configured them."""
    return [
        entry
        for entry in rails
        if str(entry.get("id", "")) in RAIL_IDS and RAIL_PHASES.get(str(entry.get("id"))) == phase
    ]


def _validators_of(rails: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The Guardrails AI entries of a rail list, in order. These run as engine actions."""
    return [entry for entry in rails if str(entry.get("id", "")) not in RAIL_IDS]


def _guard_flow_name(guard_id: str, phase: str, on_fail: str) -> str:
    """The generated flow name for one Guardrails AI validator in one phase.

    The name is built the same way in the YAML and in the Colang, and again when a triggered
    flow is mapped back to its catalog id, so the three can never disagree.
    """
    prefix = "fix" if on_fail == "fix" else "check"
    return f"{prefix} guard {guard_id.replace('_', ' ')} {phase}"


def flow_for_action(guard_id: str) -> str:
    """The engine action name that runs one Guardrails AI validator."""
    return f"check_guard_{guard_id}"


def _generated_flows(rails: list[dict[str, Any]], phase: str = "input") -> list[dict[str, Any]]:
    """One entry per flow this service generates for one phase.

    A flow is generated for every Guardrails AI validator that takes part in the phase, and for
    every rail this service implements itself (``RAIL_ACTIONS``). One table feeds the generated
    Colang, the action registration and the reverse lookup, so the three can never disagree
    about a name.

    Every phase checks the text the caller puts in the user message: this service generates
    nothing, so an answer and a retrieved passage arrive the same way as a question.
    """
    flows: list[dict[str, Any]] = []
    entries = list(_validators_of(rails)) + [
        entry for entry in _rails_of(rails, phase) if str(entry.get("id", "")) in RAIL_ACTIONS
    ]
    for entry in entries:
        guard_id = str(entry.get("id", ""))
        spec = CATALOG_BY_ID.get(guard_id)
        if spec is None or spec.get("phase") not in ("both", phase):
            continue
        flows.append(
            {
                "guard": guard_id,
                "phase": phase,
                "flow": _guard_flow_name(guard_id, phase, _on_fail(entry)),
                "action": RAIL_ACTIONS.get(guard_id) or flow_for_action(guard_id),
                # The phase decides the text under check and where a repair goes: the official
                # output rail reads and writes `bot_message`, the input rail `user_message`.
                "variable": "$bot_message" if phase == "output" else "$user_message",
                # The fact check reads the passages as well as the answer.
                "evidence": guard_id == "self_check_facts",
                "on_fail": _on_fail(entry),
            }
        )
    return flows


def build_content(
    rails: list[dict[str, Any]],
    model: str = LLM_MODEL,
    phase: str = "input",
) -> tuple[str, str]:
    """Build the engine config for one rail list and one phase.

    Every phase runs as a list of the engine's input rails over the text under check. The engine
    only fires its output rails for a bot message it generated itself, and this service generates
    nothing: it checks an answer the application already wrote. The phase is what decides which
    rails are in the list, so one config still has one rail set per phase.
    """
    models: list[dict[str, Any]] = [{"type": "main", **_model_block(model)}]
    for entry in rails:
        rail_id = str(entry.get("id", ""))
        rail_model = str((entry.get("params") or {}).get("model") or "")
        rail_type = _RAIL_MODEL_TYPES.get(rail_id)
        if rail_model and rail_type:
            models.append({"type": rail_type, **_model_block(rail_model)})

    # The self-check prompts travel with every config: the engine ships none of them, and the
    # task manager raises at render time when one is missing.
    prompts: list[dict[str, Any]] = [
        {
            "task": task,
            "content": _prompt_body(task, str(_params_of(rails, rail_id).get("policy") or "").strip()),
        }
        for rail_id, task in RAIL_PROMPTS.items()
    ]

    flows: list[str] = []
    for entry in _rails_of(rails, phase):
        rail_id = str(entry["id"])
        if rail_id == "pii_retrieval":
            # The Presidio rail runs over the text under check, so a passage and an answer both
            # arrive as the user message. The detector, the entity list and the masking are the
            # engine's own.
            flows.append("mask sensitive data on input" if _on_fail(entry) == "fix" else RAIL_FLOWS[rail_id])
            continue
        if rail_id in RAIL_ACTIONS:
            flows.append(_guard_flow_name(rail_id, phase, _on_fail(entry)))
            continue
        flows.append(RAIL_FLOWS[rail_id])

    for entry in _validators_of(rails):
        spec = CATALOG_BY_ID.get(str(entry.get("id", "")))
        if spec is None or spec.get("phase") not in ("both", phase):
            continue
        flows.append(_guard_flow_name(str(entry["id"]), phase, _on_fail(entry)))

    config: dict[str, Any] = {
        "colang_version": "1.0",
        "models": models,
        # The output phase takes the official output slot, where the runtime sets `bot_message`
        # from the message under check and a repair rail writes the checked text back. The input
        # and retrieval phases both take the input slot: the retrieval rails of the library only
        # fire when the engine computes the chunks itself, which a check-only caller never does.
        "rails": {"output" if phase == "output" else "input": {"flows": flows}},
    }
    if prompts:
        config["prompts"] = prompts

    sensitive = _sensitive_data_config(rails)
    if sensitive:
        config["rails"]["config"] = {"sensitive_data_detection": sensitive}

    return _dump_yaml(config), _dump_colang(rails, phase)


def _params_of(rails: list[dict[str, Any]], rail_id: str) -> dict[str, Any]:
    for entry in rails:
        if str(entry.get("id", "")) == rail_id:
            return dict(entry.get("params") or {})
    return {}


def _on_fail(entry: dict[str, Any]) -> str:
    return str(entry.get("on_fail") or "noop")


def _sensitive_data_config(rails: list[dict[str, Any]]) -> dict[str, Any]:
    """The Presidio rail settings, taken from the pii_retrieval parameters."""
    entry = next((e for e in rails if str(e.get("id", "")) == "pii_retrieval"), None)
    if entry is None:
        return {}
    params = dict(entry.get("params") or {})
    entities = params.get("pii_entities")
    section: dict[str, Any] = {}
    if entities:
        section["entities"] = list(entities)
    threshold = params.get("score_threshold")
    if threshold is not None:
        section["score_threshold"] = float(threshold)
    # The rail always runs over the user message, whatever the engine calls the phase.
    return {"input": section} if section else {}


def _dump_yaml(config: dict[str, Any]) -> str:
    import yaml

    return yaml.safe_dump(config, sort_keys=False, allow_unicode=True)


def _dump_colang(rails: list[dict[str, Any]], phase: str = "input") -> str:
    """One flow per generated check.

    Colang 1.0 cannot pass parameters to a flow, so a flow per guard is the only way to keep
    each guard's own parameters. The action takes the text under check as an argument, and the
    flow blocks on a verdict, or writes a repaired text back, which is how a masking guard
    changes the text the model reads.
    """
    lines: list[str] = []
    for flow in _generated_flows(rails, phase):
        args = f"text={flow['variable']}"
        if flow["evidence"]:
            args = f"{args}, evidence=$relevant_chunks"
        lines.append(f"define flow {flow['flow']}")
        lines.append(f"  $verdict = execute {flow['action']}({args})")
        lines.append("  if $verdict")
        if flow["on_fail"] == "fix":
            lines.append(f"    {flow['variable']} = $verdict")
        else:
            lines.append("    $guard_detail = $verdict")
            lines.append("    bot refuse to respond")
            lines.append("    stop")
        lines.append("")
    return "\n".join(lines)


# ── The built engine ─────────────────────────────────────────────────


def _canonical(rails: list[dict[str, Any]]) -> str:
    return json.dumps(rails, sort_keys=True, default=str)


def _register_actions(engine: Any, rails: list[dict[str, Any]]) -> None:
    for entry in _validators_of(rails):
        guard_id = str(entry.get("id", ""))

        def _make(bound: dict[str, Any], vid: str) -> Callable[..., Any]:
            async def _action(text: str = "") -> str:
                # A guard that cannot run raises here, and the phase fails open with the reason
                # in the trace. Only a verdict about the text decides the turn.
                result = run_single_validator(text, bound)
                if result["fixed_text"] and _on_fail(bound) == "fix":
                    return str(result["fixed_text"])
                if result["validation_passed"]:
                    return ""
                return str(result["detail"] or "blocked")

            return _action

        engine.register_action(_make(dict(entry), guard_id), name=flow_for_action(guard_id))

    for entry in rails:
        rail_id = str(entry.get("id", ""))
        if rail_id in RAIL_ACTIONS:
            engine.register_action(
                _judge_action(_RAIL_RUBRICS[rail_id], dict(entry)),
                name=RAIL_ACTIONS[rail_id],
            )


def _judge_action(rubric: str, entry: dict[str, Any]) -> Callable[..., Any]:
    """A rail action that scores one text with the proxy judge.

    The rail blocks when the score passes the threshold, and reports the judge's own reason, so
    the trace says why. A judge that cannot answer fails open: a broken rail must not stop every
    chat turn.
    """
    params = dict(entry.get("params") or {})
    policy = str(params.get("policy") or "").strip()
    model = str(params.get("model") or "")
    body = f"{rubric}\n\nPolicy:\n{policy}" if policy else rubric
    system = (
        f"{body}\n"
        "Score from 0.0 (no problem) to 1.0 (clear problem). "
        'Reply with JSON only: {"score": <number>, "reason": "<short reason>"}'
    )

    async def _action(text: str = "", evidence: str = "") -> str:
        payload = f"PASSAGES:\n{evidence}\n\nANSWER:\n{text}" if evidence else text
        # A judge that cannot answer raises here. The engine logs it, the phase fails open with
        # the reason in the trace, and the turn still runs.
        verdict = _ask_judge(system, payload, model)
        score = float(verdict.get("score") or 0.0)
        if score <= _RAIL_THRESHOLD:
            return ""
        reason = str(verdict.get("reason") or "").strip()
        return f"{reason} (score {score:.2f})" if reason else f"Score {score:.2f}"

    return _action


@lru_cache(maxsize=64)
def _build_cached(canonical: str, model: str, facts: bool, phase: str) -> Any:
    """Build one engine. Cached by the canonical rail list, the model, the facts flag and phase.

    RailsConfig validates the prompts and parses the Colang on every construction, so a request
    must never build one.
    """
    if RailsConfig is None or LLMRails is None:
        raise EngineUnavailable(NEMO_IMPORT_ERROR or "nemoguardrails is not installed")

    rails: list[dict[str, Any]] = json.loads(canonical)
    if not facts:
        rails = [e for e in rails if str(e.get("id", "")) != "self_check_facts"]
    yaml_content, colang_content = build_content(rails, model, phase)
    config = RailsConfig.from_content(yaml_content=yaml_content, colang_content=colang_content)
    engine = LLMRails(config, verbose=False)
    _register_actions(engine, rails)
    return engine


def rails_for(
    rails: list[dict[str, Any]],
    model: str = LLM_MODEL,
    *,
    facts: bool = True,
    phase: str = "input",
) -> Any:
    """The engine for one rail list and phase, built once and reused."""
    return _build_cached(_canonical(rails), model, facts, phase)


# ── Checking one phase ───────────────────────────────────────────────


def _rail_timings(log: Any) -> dict[str, int]:
    """Activated rail name -> milliseconds, from the engine's own log."""
    timings: dict[str, int] = {}
    for rail in _field(log, "activated_rails") or []:
        name = _field(rail, "name") or _field(rail, "type")
        if not name:
            continue
        ms: int | None = None
        duration = _field(rail, "duration")
        if isinstance(duration, (int, float)):
            ms = int(float(duration) * 1000)
        else:
            started, finished = _field(rail, "started_at"), _field(rail, "finished_at")
            if isinstance(started, (int, float)) and isinstance(finished, (int, float)):
                ms = int((finished - started) * 1000)
        if ms is not None:
            timings[str(name)] = ms
    return timings


def _stopped_rail(log: Any) -> str:
    """The flow the engine stopped on, from the log, when it says so."""
    for rail in _field(log, "activated_rails") or []:
        if _field(rail, "stop"):
            return str(_field(rail, "name") or "")
    return ""


def _field(result: Any, name: str) -> Any:
    """Read one field from an engine result. The engine answers with a dict or an object.

    `generate` returns a dict when `output_vars` is set, and an object on the plain path; the
    check API returns an object. Reading both shapes keeps the mapping in one place.
    """
    if isinstance(result, dict):
        return result.get(name)
    return getattr(result, name, None)


def _output_data(result: Any) -> dict[str, Any]:
    for name in ("output_data", "context"):
        data = _field(result, name)
        if isinstance(data, dict):
            return data
    return {}


def _blocking_flow(rails: list[dict[str, Any]], phase: str, data: dict[str, Any]) -> str | None:
    """The flow the engine stopped on, mapped back to its catalog id."""
    for key in ("triggered_input_rail", "triggered_output_rail", "triggered_retrieval_rail"):
        name = data.get(key)
        if not name:
            continue
        return _flow_to_guard(rails, str(name), phase)
    return None


def _flow_to_guard(rails: list[dict[str, Any]], flow_name: str, phase: str = "input") -> str | None:
    """The catalog id of the guard that owns a flow name, or None."""
    ids = {str(entry.get("id", "")) for entry in rails}
    for rail_id, flow in RAIL_FLOWS.items():
        if flow == flow_name and rail_id in ids:
            return rail_id
    # The retrieval phase runs the Presidio input rail, whose flow name is not the rail id.
    if flow_name == "mask sensitive data on input" and "pii_retrieval" in ids:
        return "pii_retrieval"
    for flow in _generated_flows(rails, phase):
        if flow["flow"] == flow_name:
            return flow["guard"]
    return None


class RailLogCapture(logging.Handler):
    """Collect one engine call's own action errors, keyed by the action that failed.

    An action that raises is caught by the engine, logged, and reported as nothing at all, so the
    log is the only place the reason survives. The reason belongs in the trace, and the rail has
    to fail open: a broken guard must not block every turn.
    """

    _ACTION = re.compile(r"Error while execution '([^']+)'")

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.errors: dict[str, str] = {}

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        match = self._ACTION.search(message)
        if match:
            self.errors.setdefault(match.group(1), message[:300])


def _guard_for_action(action_name: str) -> str | None:
    """The catalog id behind an engine action name, or None."""
    if action_name.startswith("check_guard_"):
        return action_name[len("check_guard_") :]
    for rail_id, action in RAIL_ACTIONS.items():
        if action == action_name:
            return rail_id
    return None


def _check_once(
    engine: Any,
    *,
    phase: str,
    text: str,
    query: str | None,
    answer: str | None,
    chunks: list[str],
    check_facts: bool = False,
) -> dict[str, Any]:
    """Run one engine call. Returns the output variables, the rail timings and the stop rail."""
    context: dict[str, Any] = {}
    if phase == "output":
        # The official post-hoc shape: the question is the user message and the answer to check
        # is the assistant message, from which the runtime sets `bot_message`. The context
        # carries what only this service knows: the passages and the facts flag.
        context = {
            "relevant_chunks": "\n\n".join(chunks),
            "check_facts": check_facts,
        }
    # The context message must come first: with it last, the engine runs no rails at all.
    messages: list[dict[str, Any]] = []
    if context:
        messages.append({"role": "context", "content": context})
    if phase == "output":
        messages.append({"role": "user", "content": query or text})
        messages.append({"role": "assistant", "content": answer if answer is not None else text})
    else:
        messages.append({"role": "user", "content": text})

    # The engine logs an action failure and then reports nothing, so its own log is the only
    # place the reason survives. The rail must fail open, and the trace must say why.
    capture = RailLogCapture()
    engine_log = logging.getLogger("nemoguardrails.actions.action_dispatcher")
    engine_log.addHandler(capture)
    try:
        result = engine.generate(
            messages=messages,
            options={
                "rails": ["output" if phase == "output" else "input"],
                "output_vars": [
                    "triggered_input_rail",
                    "triggered_output_rail",
                    "triggered_retrieval_rail",
                    "guard_detail",
                    "user_message",
                    "bot_message",
                ],
                "log": {"activated_rails": True},
            },
        )
    finally:
        engine_log.removeHandler(capture)
    log = _field(result, "log")
    return {
        "data": _output_data(result),
        "timings": _rail_timings(log),
        "stopped": _stopped_rail(log),
        "action_errors": capture.errors,
    }


def _pass_result(**extra: Any) -> dict[str, Any]:
    return {"validation_passed": True, "error": None, "detail": None, **extra}


def check_phase(
    *,
    rails: list[dict[str, Any]],
    phase: str,
    text: str,
    model: str = LLM_MODEL,
    query: str | None = None,
    answer: str | None = None,
    chunks: list[str] | None = None,
) -> dict[str, Any]:
    """Run one phase and return the engine's result map, in the shape callers already read."""
    if phase == "both":
        # A caller that names no phase wants the whole config to run, which is both check
        # points. The offline evaluation uses this: one dataset row and no chat turn.
        runs = {
            one: check_phase(
                rails=rails, phase=one, text=text, model=model, query=query, answer=answer, chunks=chunks
            )
            for one in ("input", "output")
        }
        blocker = next((one for one in ("input", "output") if runs[one]["blocked"]), None)
        merged: dict[str, dict[str, Any]] = {}
        for one in ("input", "output"):
            merged.update(runs[one]["results"])
        return {
            "validation_passed": blocker is None,
            "blocked": blocker is not None,
            "blocked_by": runs[blocker]["blocked_by"] if blocker else None,
            "phase": phase,
            "results": merged,
            "chunks": runs["output"]["chunks"] or runs["input"]["chunks"],
            "text": runs["output"].get("text") or runs["input"].get("text"),
        }

    passages = [p for p in (chunks or []) if p]
    facts_rail = "self_check_facts" in {str(e.get("id", "")) for e in rails}
    facts_skipped = phase == "output" and facts_rail and not passages

    engine = rails_for(rails, model, facts=not facts_skipped, phase=phase)

    results: dict[str, dict[str, Any]] = {str(entry.get("id", "")): _pass_result() for entry in rails}

    timings: dict[str, int] = {}
    blocked_by: str | None = None
    masked: list[str] | None = None
    guard_detail: str | None = None
    fixed: str | None = None

    try:
        if phase == "retrieval":
            joined = "\n\n".join(passages) if passages else text
            run = _check_once(engine, phase=phase, text=joined, query=query, answer=answer, chunks=passages)
            data, timings = run["data"], run["timings"]
            blocked_by = _blocking_flow(rails, phase, data) or _flow_to_guard(rails, run["stopped"] or "")
            masked_text = str(data.get("user_message") or "")
            if masked_text and masked_text != joined:
                # Masking keeps the separator, so the passages stay in order and in count.
                split = masked_text.split("\n\n")
                masked = split if len(split) == len(passages) else [masked_text]
        else:
            run = _check_once(
                engine,
                phase=phase,
                text=text,
                query=query,
                answer=answer,
                chunks=passages,
                check_facts=facts_rail and not facts_skipped,
            )
            data, timings = run["data"], run["timings"]
            blocked_by = _blocking_flow(rails, phase, data) or _flow_to_guard(rails, run["stopped"] or "")
            guard_detail = str(data.get("guard_detail") or "") or None
            if blocked_by is None:
                # A repair rail on this phase writes the text under check back to `bot_message`,
                # the official output variable, so the caller returns the repaired answer.
                repaired = str(data.get("bot_message") or "")
                if repaired and repaired != (answer if answer is not None else text):
                    fixed = repaired
    except Exception as exc:  # noqa: BLE001 - a rail failure must not block every turn
        logger.exception("Rail phase %s failed: %s", phase, exc)
        for rail_id in list(results):
            results[rail_id] = {"validation_passed": True, "error": f"{type(exc).__name__}: {exc}"[:200], "detail": None}
        return {
            "validation_passed": True,
            "blocked": False,
            "blocked_by": None,
            "phase": phase,
            "results": results,
            "chunks": None,
            "text": None,
        }

    # A guard whose action raised is not a verdict about the text, so it reports the reason and
    # the phase fails open. This runs before the mapping below, which would call the same guard a
    # clean pass.
    failed: dict[str, str] = {}
    for action_name, message in (run.get("action_errors") or {}).items():
        guard_id = _guard_for_action(action_name)
        if guard_id and guard_id in results:
            failed[guard_id] = str(message)[:300]
            if blocked_by == guard_id:
                blocked_by = None

    activated = set(timings)
    for entry in rails:
        rail_id = str(entry.get("id", ""))
        if rail_id in failed:
            results[rail_id] = {"validation_passed": True, "error": failed[rail_id], "detail": None}
            continue
        if rail_id == blocked_by:
            results[rail_id] = {
                "validation_passed": False,
                "error": None,
                "detail": guard_detail or "blocked",
                "ms": timings.get(_rail_flow_name(rails, rail_id, phase) or "", 0),
            }
            continue
        flow = _rail_flow_name(rails, rail_id, phase)
        if flow and flow in activated:
            results[rail_id] = _pass_result(ms=timings[flow])
        elif flow and activated:
            # The log says what ran, so a rail that is missing from it did not run. Without a
            # log, the verdict is simply unknown, and a pass is the only safe report.
            results[rail_id] = _pass_result(detail=_NOT_RUN if blocked_by else None)

    if facts_skipped:
        results["self_check_facts"] = _pass_result(detail=_FACTS_SKIPPED)

    return {
        "validation_passed": blocked_by is None,
        "blocked": blocked_by is not None,
        "blocked_by": blocked_by,
        "phase": phase,
        "results": results,
        "chunks": masked,
        "text": fixed,
    }


def _rail_flow_name(rails: list[dict[str, Any]], rail_id: str, phase: str) -> str | None:
    """The flow that a catalog id maps to in this config and phase, or None for a validator."""
    entry = next((e for e in rails if str(e.get("id", "")) == rail_id), None)
    if rail_id in RAIL_FLOWS:
        # The retrieval phase uses the masking rail when the failure action repairs text.
        if rail_id == "pii_retrieval" and entry is not None and _on_fail(entry) == "fix":
            return "mask sensitive data on input"
        return RAIL_FLOWS[rail_id]
    if entry is None:
        return None
    for flow in _generated_flows(rails, phase):
        if flow["guard"] == rail_id and flow["phase"] == phase:
            return flow["flow"]
    return None


# ── The endpoint entry point ─────────────────────────────────────────


def _applies(entry: dict[str, Any], phase: str) -> bool:
    """Does this catalog entry belong to this phase?

    A validator declares `both` unless the catalog says otherwise, and it keeps the phase
    meaning it has today. A rail declares exactly one phase. The default `both` phase means the
    caller did not name a phase, so nothing is filtered.
    """
    if phase not in ("input", "retrieval", "output"):
        return True
    vid = str(entry.get("id", ""))
    spec = CATALOG_BY_ID.get(vid) or {}
    entry_phase = RAIL_PHASES.get(vid) or spec.get("phase") or "both"
    if phase == "retrieval":
        return entry_phase == "retrieval"
    return entry_phase in ("both", phase)


def run_check(
    text: str,
    validators: list[dict[str, Any]],
    phase: str = "both",
    *,
    query: str | None = None,
    answer: str | None = None,
    chunks: list[str] | None = None,
) -> dict[str, Any]:
    """Run one phase for the /validate endpoint.

    A phase with no applicable entry runs nothing and reports `skipped`, so a caller can ask
    for a phase on every turn without paying for it. A phase with no rail takes the old path,
    unchanged and without touching the engine. A phase with any rail takes the engine path,
    where the configured validators run as engine actions.
    """
    applicable = [entry for entry in validators if _applies(entry, phase)]
    applicable_ids = {str(entry.get("id", "")) for entry in applicable}
    # A caller keys its own results by the guard list it sent, so every guard it sent comes back
    # with a verdict. A guard that has no place in this phase reports that, rather than going
    # missing and looking like a broken rail.
    other_phase = {
        str(entry.get("id", "")): _pass_result(detail=_NOT_IN_PHASE)
        for entry in validators
        if str(entry.get("id", "")) not in applicable_ids
    }

    if not applicable:
        return {
            "validation_passed": True,
            "blocked": False,
            "blocked_by": None,
            "phase": phase,
            "results": other_phase,
            "chunks": None,
            "text": None,
            "skipped": True,
        }

    has_rail = any(str(entry.get("id", "")) in RAIL_IDS for entry in applicable)
    if NEMO_IMPORT_ERROR or not has_rail:
        outcome = run_validators(text, applicable, phase=phase)
        outcome["chunks"] = None
        outcome["text"] = None
        outcome["skipped"] = False
        outcome["results"].update(other_phase)
        return outcome

    started = time.perf_counter()
    outcome = check_phase(
        rails=applicable,
        phase=phase,
        text=text,
        query=query,
        answer=answer,
        chunks=chunks,
    )
    outcome["results"].update(other_phase)
    outcome["engine_ms"] = int((time.perf_counter() - started) * 1000)
    outcome["skipped"] = False
    return outcome
