"""Validator catalog and guard construction for the guardrails service.

The catalog holds three validators. Two are real Guardrails AI validators, installed from
public PyPI as ``guardrails-ai-<name>``: ``ban_list`` and ``detect_pii``. The old
``guardrails hub install`` CLI and its private registry are deprecated, and the old
``from guardrails.hub import X`` shim is scheduled for removal.

``toxic_language`` is a local implementation of the Guardrails ``Validator`` interface,
registered under the ``local/toxic_language`` alias. It judges text with the LiteLLM proxy
that the rest of the platform already uses. The upstream package needs PyTorch and several
gigabytes of CUDA libraries, so it is deliberately not installed.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
from functools import lru_cache
from typing import Any

from guardrails import Guard
from guardrails.validator_base import (
    FailResult,
    PassResult,
    Validator,
    get_validator_class,
    register_validator,
)

logger = logging.getLogger(__name__)

LLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "http://host.docker.internal:4000").rstrip("/")
LLM_API_KEY = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or "sk-bot"
# Gpt-oss-20b is the measured model: 18 of 18 correct in 1 to 3 seconds. Gpt-oss-120b was
# tried and rejected, because it took 8 to 105 seconds and often timed out.
LLM_MODEL = os.environ.get("GUARDRAIL_LLM_MODEL", "Gpt-oss-20b")
# One judge call's own bound. A rail that sends a long text needs the headroom: the scope rail
# sends the whole prompt template (about 1.4 KB), and its judge measured 10.4 s on a blocking
# call. At 20 s one call timed out, and the rail then failed open with no verdict at all.
LLM_TIMEOUT_S = float(os.environ.get("GUARDRAIL_LLM_TIMEOUT_S", "25"))

# The judge models are reasoning models: the budget must cover the reasoning chain and the
# JSON answer, or the body comes back empty. Measured on a 5.6 KB fact-check payload, 1039
# completion tokens, 1007 of them reasoning; 512 and 1024 both returned an empty body. 2048
# leaves headroom for that payload. A payload much larger than that needs a larger budget.
LLM_MAX_TOKENS = int(os.environ.get("GUARDRAIL_LLM_MAX_TOKENS", "2048"))

# NeMo Guardrails is the rail engine. It is optional, exactly like a Hub validator package:
# when the import fails the service still serves the validators below, and the catalog marks
# every rail unavailable with this reason. The message is reported, never raised.
try:
    import nemoguardrails  # noqa: F401

    NEMO_IMPORT_ERROR: str | None = None
except Exception as _exc:  # noqa: BLE001 - a missing engine must not stop the service
    NEMO_IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"[:200]


# ── LLM judges, backed by the local LiteLLM proxy ────────────────────


def _ask_judge(system: str, text: str, model: str) -> dict[str, Any]:
    """Ask the judge model for a JSON verdict. Raises on a transport or parse failure."""
    import httpx

    response = httpx.post(
        f"{LLM_BASE_URL}/v1/chat/completions",
        headers={"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": model or LLM_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": f"TEXT:\n{text}"},
            ],
            "max_tokens": LLM_MAX_TOKENS,
            "temperature": 0,
        },
        timeout=LLM_TIMEOUT_S,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"] or ""
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end < start:
        raise ValueError(
            f"Judge returned no JSON. Model {model or LLM_MODEL} replied with "
            f"{len(content)} characters: {content[:100]!r}"
        )
    return json.loads(content[start : end + 1])


class _LlmJudge(Validator):
    """Shared plumbing for the three judge-backed validators."""

    # Subclasses set the rubric.
    rubric: str = ""

    def __init__(self, threshold: float = 0.5, model: str = "", on_fail: Any = "noop", **kwargs: Any):
        super().__init__(on_fail=on_fail, threshold=threshold, model=model, **kwargs)
        self.threshold = float(threshold)
        self.model = model

    def _score(self, value: Any) -> float:
        verdict = _ask_judge(self._system(), str(value), self.model)
        return float(verdict.get("score", 0.0))

    def _system(self) -> str:
        return (
            f"{self.rubric}\n"
            "Score from 0.0 (completely safe) to 1.0 (clearly violating). "
            'Reply with JSON only: {"score": <number>, "reason": "<short reason>"}'
        )

    def validate(self, value: Any, metadata: dict | None = None) -> Any:
        try:
            score = self._score(value)
        except Exception as exc:  # transport, auth, or parse failure
            # Fail open. A judge outage must not block every chat turn, and the caller
            # records the error so it shows up in the trace instead of silently passing.
            return PassResult(value_override=None, metadata={"judge_error": str(exc)[:200]})

        if score > self.threshold:
            return FailResult(error_message=f"LLM judge score {score:.2f} exceeds {self.threshold:.2f}")
        return PassResult()


@register_validator(name="local/toxic_language", data_type="string")
class LlmToxicLanguage(_LlmJudge):
    """Flag abusive, harassing, or threatening text. Replaces the PyTorch Detoxify model."""

    rubric = (
        "You classify text for toxicity. Rate abuse, harassment, threats, insults, and "
        "degrading language aimed at a person. Do not rate disagreement, criticism, or "
        "profanity-free negative opinions as toxic."
    )


# ── Catalog ──────────────────────────────────────────────────────────

# The Presidio entity types offered by the two PII guards. One list, so the validator guard
# and the retrieval rail never drift apart.
PII_ENTITY_OPTIONS: list[dict[str, str]] = [
    {"id": "EMAIL_ADDRESS", "label": "Email Address"},
    {"id": "PHONE_NUMBER", "label": "Phone Number"},
    {"id": "CREDIT_CARD", "label": "Credit Card"},
    {"id": "US_SSN", "label": "US SSN"},
    {"id": "IP_ADDRESS", "label": "IP Address"},
    {"id": "PERSON", "label": "Person Name"},
    {"id": "LOCATION", "label": "Location"},
    {"id": "DATE_TIME", "label": "Date / Time"},
    {"id": "URL", "label": "URL"},
    {"id": "DOMAIN_NAME", "label": "Domain Name"},
    {"id": "US_PASSPORT", "label": "US Passport"},
    {"id": "US_DRIVER_LICENSE", "label": "US Driver License"},
    {"id": "US_BANK_NUMBER", "label": "US Bank Number"},
    {"id": "US_ITIN", "label": "US ITIN"},
    {"id": "IBAN_CODE", "label": "IBAN Code"},
    {"id": "CRYPTO", "label": "Crypto Wallet"},
    {"id": "MEDICAL_LICENSE", "label": "Medical License"},
    {"id": "NRP", "label": "Nationality / Religion / Political group"},
]

# Each entry maps one catalog id to one real validator. `module` is imported at startup so
# @register_validator runs; `alias` is then resolvable through get_validator_class.
_VALIDATORS: list[dict[str, Any]] = [
    {
        "id": "ban_list",
        "label": "Ban List",
        "description": "Block a list of words or phrases. Matching ignores case and spacing.",
        "category": "Content Safety",
        "phase": "both",
        "kind": "local",
        "module": "guardrails_ai.ban_list",
        "alias": "guardrails/ban_list",
        "package": "guardrails-ai-ban-list",
        "params": [
            {
                "name": "banned_words",
                "type": "string_list",
                "label": "Banned words",
                "help": "Words or phrases that must not appear in the text.",
                "required": True,
                "default": [],
            },
            {
                "name": "max_l_dist",
                "type": "integer",
                "label": "Fuzzy distance",
                "help": "How many character edits still count as a match. 0 means an exact substring.",
                "required": False,
                "default": 0,
                "min": 0,
                "max": 5,
            },
        ],
    },
    {
        "id": "detect_pii",
        "label": "PII Detection",
        "description": "Detect personal data with Presidio: emails, phone numbers, cards, and more.",
        "category": "Privacy",
        "phase": "both",
        "kind": "model",
        "module": "guardrails_ai.detect_pii",
        "alias": "guardrails/detect_pii",
        "package": "guardrails-ai-detect-pii",
        "params": [
            {
                "name": "pii_entities",
                "type": "string_list",
                "label": "PII types",
                "help": "Entity types to look for. Pick from the list.",
                "required": True,
                "default": ["EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "US_SSN", "IP_ADDRESS"],
                "options": PII_ENTITY_OPTIONS,
            },
        ],
    },
    {
        "id": "toxic_language",
        "label": "Toxic Language",
        "description": "Flag abusive, harassing, or threatening text with an LLM judge.",
        "category": "Content Safety",
        "phase": "both",
        "kind": "llm",
        "module": None,
        "alias": "local/toxic_language",
        "package": None,
        "params": [
            {
                "name": "threshold",
                "type": "number",
                "label": "Sensitivity",
                "help": "Block when the judge score is above this. Lower blocks more text.",
                "required": False,
                "default": 0.5,
                "min": 0.0,
                "max": 1.0,
            },
            {
                "name": "model",
                "type": "string",
                "label": "Judge model",
                "help": f"Leave empty to use {LLM_MODEL}.",
                "required": False,
                "default": "",
            },
        ],
    },
]

# ── NeMo rails ───────────────────────────────────────────────────────

# The rails the engine runs itself. A rail is not a Guardrails AI validator, so it has no
# module and no alias: the engine implements it. `rail: True` tells the module check to ask
# about the engine instead of a Hub package. The catalog drives the Guard Config page, so a
# rail is configured exactly like a validator: same param schema, same on_fail options.
RAIL_SPECS: list[dict[str, Any]] = [
    {
        "id": "self_check_input",
        "label": "Self Check Input",
        "description": "Ask a judge model whether the user message is allowed, before retrieval runs.",
        "category": "Content Safety",
        "phase": "input",
        "kind": "llm",
        "rail": True,
        "params": [
            {
                "name": "policy",
                "type": "text",
                "label": "Policy",
                "help": "What the message must not do. Leave empty for the default policy.",
                "required": False,
                "default": "",
            },
            {
                "name": "model",
                "type": "string",
                "label": "Judge model",
                "help": f"Leave empty to use {LLM_MODEL}. A rail spends one model call per turn.",
                "required": False,
                "default": "",
            },
        ],
    },
    {
        "id": "jailbreak_heuristics",
        "label": "Jailbreak Heuristics",
        "description": "Catch instruction-override attempts (role play, ignore your rules, developer mode).",
        "category": "Content Safety",
        "phase": "input",
        "kind": "llm",
        "rail": True,
        "params": [
            {
                "name": "policy",
                "type": "text",
                "label": "Policy",
                "help": "What counts as an override attempt. Leave empty for the default policy.",
                "required": False,
                "default": "",
            },
            {
                "name": "model",
                "type": "string",
                "label": "Judge model",
                "help": f"Leave empty to use {LLM_MODEL}. This rail spends one model call per turn.",
                "required": False,
                "default": "",
            },
        ],
    },
    {
        "id": "template_scope",
        "label": "Template Scope",
        "description": "Check the message against the scope the pipeline's prompt template declares.",
        "category": "Topic Control",
        "phase": "input",
        "kind": "llm",
        "rail": True,
        "params": [
            {
                "name": "policy",
                "type": "text",
                "label": "Scope",
                "help": "What this assistant is for. A pipeline's prompt template fills this in.",
                "required": False,
                "default": "",
            },
            {
                "name": "model",
                "type": "string",
                "label": "Judge model",
                "help": f"Leave empty to use {LLM_MODEL}. A rail spends one model call per turn.",
                "required": False,
                "default": "",
            },
        ],
    },
    {
        "id": "pii_retrieval",
        "label": "PII in Retrieved Chunks",
        "description": "Check the passages retrieved for this question. Use Repair to mask, or Block to stop the turn.",
        "category": "Privacy",
        "phase": "retrieval",
        "kind": "model",
        "rail": True,
        "params": [
            {
                "name": "pii_entities",
                "type": "string_list",
                "label": "PII types",
                "help": "Entity types to look for. Pick from the list.",
                "required": False,
                "default": ["EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "US_SSN", "IP_ADDRESS"],
                "options": PII_ENTITY_OPTIONS,
            },
            {
                "name": "score_threshold",
                "type": "number",
                "label": "Confidence",
                "help": "Ignore a hit below this confidence. Lower finds more.",
                "required": False,
                "default": 0.2,
                "min": 0.0,
                "max": 1.0,
            },
        ],
    },
    {
        "id": "self_check_output",
        "label": "Self Check Output",
        "description": "Ask a judge model whether the finished answer is allowed, before the user sees it.",
        "category": "Content Safety",
        "phase": "output",
        "kind": "llm",
        "rail": True,
        "params": [
            {
                "name": "policy",
                "type": "text",
                "label": "Policy",
                "help": "What the answer must not do. Leave empty for the default policy.",
                "required": False,
                "default": "",
            },
            {
                "name": "model",
                "type": "string",
                "label": "Judge model",
                "help": f"Leave empty to use {LLM_MODEL}. A rail spends one model call per turn.",
                "required": False,
                "default": "",
            },
        ],
    },
    {
        "id": "self_check_facts",
        "label": "Fact Check Against Sources",
        "description": "Check that the answer is supported by the retrieved passages. Needs a retrieval phase with passages.",
        "category": "Grounding",
        "phase": "output",
        "kind": "llm",
        "rail": True,
        "params": [
            {
                "name": "policy",
                "type": "text",
                "label": "Policy",
                "help": "What counts as unsupported. Leave empty for the default policy.",
                "required": False,
                "default": "",
            },
            {
                "name": "model",
                "type": "string",
                "label": "Judge model",
                "help": f"Leave empty to use {LLM_MODEL}.",
                "required": False,
                "default": "",
            },
        ],
    },
]

_VALIDATORS.extend(RAIL_SPECS)

ON_FAIL_OPTIONS: list[dict[str, Any]] = [
    {
        "id": "noop",
        "label": "Block the request",
        "help": "Record the failure and stop the chat turn. Recommended, and the default.",
        "fixes_text": False,
    },
    {
        "id": "exception",
        "label": "Block and raise an error",
        "help": "Same effect, but the validator raises instead of returning.",
        "fixes_text": False,
    },
    {
        "id": "fix",
        "label": "Repair the text and continue",
        "help": "Rewrite the text, for example to lowercase it, and continue the turn. Only some validators support this.",
        "fixes_text": True,
    },
]

_ON_FAIL_IDS = {o["id"] for o in ON_FAIL_OPTIONS}

# id -> spec, for validation.
CATALOG_BY_ID: dict[str, dict[str, Any]] = {v["id"]: v for v in _VALIDATORS}


def _module_state() -> dict[str, str | None]:
    """Import each validator module once. Return id -> import error, or None when it loaded."""
    state: dict[str, str | None] = {}
    for spec in _VALIDATORS:
        if spec.get("rail"):
            # A rail is implemented by the engine, so it needs no Hub package.
            state[spec["id"]] = NEMO_IMPORT_ERROR
            continue
        module = spec.get("module")
        if not module:
            state[spec["id"]] = None  # local implementation, always present
            continue
        try:
            importlib.import_module(module)
            state[spec["id"]] = None
        except Exception as exc:
            logger.error("Validator %s is unavailable: %s", spec["id"], exc)
            state[spec["id"]] = f"{type(exc).__name__}: {exc}"[:200]
    return state


_MODULE_STATE = _module_state()


def get_catalog() -> dict[str, Any]:
    """The validator catalog, with availability resolved against this installation."""
    validators = []
    for spec in _VALIDATORS:
        reason = _MODULE_STATE.get(spec["id"])
        entry = {k: v for k, v in spec.items() if k not in ("module", "package")}
        entry["available"] = reason is None
        entry["unavailable_reason"] = reason
        entry["package"] = spec.get("package")
        validators.append(entry)
    return {"version": 1, "validators": validators, "on_fail_options": ON_FAIL_OPTIONS}


def _coerce(spec: dict[str, Any], param: dict[str, Any], value: Any) -> Any:
    """Turn one JSON value into the Python value the validator constructor expects."""
    kind = param["type"]
    name = param["name"]
    where = f"{spec['id']}.{name}"

    if kind == "string_list":
        if isinstance(value, str):
            value = [p.strip() for p in value.split(",") if p.strip()]
        if not isinstance(value, list):
            raise ValueError(f"{where} must be a list of strings")
        items = [str(v).strip() for v in value if str(v).strip()]
        options = param.get("options")
        if options:
            allowed = {o["id"] for o in options}
            bad = [i for i in items if i not in allowed]
            if bad:
                raise ValueError(f"{where} has unknown values: {', '.join(bad)}")
        return items

    if kind == "integer":
        if value in (None, ""):
            return None
        return int(value)

    if kind == "number":
        if value in (None, ""):
            return None
        return float(value)

    if kind == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)

    if kind == "select":
        options = param.get("options") or []
        if value in (None, ""):
            return param.get("default")
        if value not in {o["id"] for o in options}:
            raise ValueError(f"{where} must be one of: {', '.join(o['id'] for o in options)}")
        return str(value)

    if value is None:
        return None
    return str(value)


def coerce_params(spec: dict[str, Any], raw: dict[str, Any] | None) -> dict[str, Any]:
    """Validate and coerce one validator's parameters. Raises ValueError with a usable message."""
    raw = raw or {}
    known = {p["name"] for p in spec["params"]}
    unknown = [k for k in raw if k not in known and k != "on_fail"]
    if unknown:
        raise ValueError(f"{spec['id']} has unknown parameters: {', '.join(sorted(unknown))}")

    out: dict[str, Any] = {}
    for param in spec["params"]:
        name = param["name"]
        present = name in raw and raw[name] not in (None, "", [])
        if not present:
            if param.get("required"):
                label = param.get("label") or name
                raise ValueError(f"{spec['label']}: '{label}' is required")
            # Only pass optional params that have a real default, so the validator's own
            # default applies when the user leaves the field empty.
            default = param.get("default")
            if default not in (None, ""):
                out[name] = default
            continue
        out[name] = _coerce(spec, param, raw[name])
    return out


@lru_cache(maxsize=256)
def _instance(alias: str, params_key: str, on_fail: str) -> Validator:
    """Build (or reuse) one validator instance.

    Cached because DetectPII loads a spaCy pipeline in its constructor. Rebuilding it per
    request would reload the model on every chat turn.
    """
    cls = get_validator_class(alias)
    if cls is None:
        raise ValueError(f"Unknown validator: {alias}")
    return cls(on_fail=on_fail, **json.loads(params_key))


def build_guard(validators: list[dict[str, Any]], name: str = "guardrails-config") -> tuple[Guard, list[str]]:
    """Build one Guard. Returns the guard and the catalog ids in the order they were added.

    `Guard.use()` REPLACES the validator list when called repeatedly. All instances must go
    into a single call, so this function collects them first.
    """
    instances: list[Validator] = []
    ids: list[str] = []

    for entry in validators:
        vid = str(entry.get("id", ""))
        spec = CATALOG_BY_ID.get(vid)
        if spec is None:
            raise ValueError(f"Unknown validator id: {vid}")
        reason = _MODULE_STATE.get(vid)
        if reason:
            raise ValueError(f"{spec['label']} is not installed: {reason}")

        on_fail = str(entry.get("on_fail") or "noop")
        if on_fail not in _ON_FAIL_IDS:
            raise ValueError(f"{vid}.on_fail must be one of: {', '.join(sorted(_ON_FAIL_IDS))}")

        params = coerce_params(spec, entry.get("params"))
        key = json.dumps(params, sort_keys=True)
        instances.append(_instance(spec["alias"], key, on_fail))
        ids.append(vid)

    if not instances:
        raise ValueError("At least one validator is required")

    guard = Guard(name=name)
    guard.use(*instances)
    return guard, ids


def validate_validators(validators: list[dict[str, Any]]) -> list[str]:
    """Return a list of problems with a validator list. Empty means the list is buildable.

    The config API calls this before it saves, so a bad parameter is rejected at save time
    rather than surfacing later on a chat turn.
    """
    errors: list[str] = []
    for entry in validators:
        vid = str(entry.get("id", ""))
        spec = CATALOG_BY_ID.get(vid)
        if spec is None:
            errors.append(f"Unknown validator id: {vid}")
            continue
        reason = _MODULE_STATE.get(vid)
        if reason:
            errors.append(f"{spec['label']} is not installed: {reason}")
            continue
        on_fail = str(entry.get("on_fail") or "noop")
        if on_fail not in _ON_FAIL_IDS:
            errors.append(f"{vid}.on_fail must be one of: {', '.join(sorted(_ON_FAIL_IDS))}")
        try:
            coerce_params(spec, entry.get("params"))
        except ValueError as exc:
            errors.append(str(exc))
    return errors


def run_validators(text: str, validators: list[dict[str, Any]], phase: str = "both") -> dict[str, Any]:
    """Run every validator over the text and return a per-validator result map."""
    guard, ids = build_guard(validators)
    outcome = guard.parse(text)
    logs = guard.history.last.validator_logs if guard.history.last else []

    results: dict[str, dict[str, Any]] = {}
    for index, vid in enumerate(ids):
        log = logs[index] if index < len(logs) else None
        if log is None:
            results[vid] = {"validation_passed": True, "error": None, "detail": None}
            continue
        passed = "pass" in str(log.validation_result.outcome).lower()
        message = getattr(log.validation_result, "error_message", None)
        # The judge reports a transport failure through this metadata key. Surface it as an
        # error so it is visible, and keep the check itself as passed.
        judge_error = (log.validation_result.metadata or {}).get("judge_error") if passed else None
        results[vid] = {
            "validation_passed": passed,
            "error": judge_error,
            "detail": None if passed else (str(message) if message else "blocked"),
        }

    blocked_by = next((vid for vid, r in results.items() if not r["validation_passed"]), None)
    return {
        "validation_passed": all(r["validation_passed"] for r in results.values()),
        "blocked": blocked_by is not None,
        "blocked_by": blocked_by,
        "phase": phase,
        "results": results,
    }


def run_single_validator(text: str, entry: dict[str, Any]) -> dict[str, Any]:
    """Run one validator from the catalog over the text.

    The rail engine calls this once per configured validator, so the engine decides when the
    validator runs and what its failure does, and one validator's verdict never hides another's.
    Returns ``validation_passed``, ``error``, ``detail`` and ``fixed_text``. ``fixed_text``
    holds the repaired text of a ``fix`` validator, which ``run_validators`` drops because it
    reads only the log.
    """
    vid = str(entry.get("id", ""))
    if CATALOG_BY_ID.get(vid) is None:
        raise ValueError(f"Unknown validator id: {vid}")

    # Building stays outside the try: a missing package or a bad parameter is the caller's
    # problem, not a verdict about the text.
    guard, _ = build_guard([entry])

    try:
        outcome = guard.parse(text)
    except Exception as exc:
        # on_fail=exception raises instead of returning a failure. That is a block.
        return {
            "validation_passed": False,
            "error": None,
            "detail": f"{type(exc).__name__}: {exc}"[:300],
            "fixed_text": None,
        }

    logs = guard.history.last.validator_logs if guard.history.last else []
    if not logs:
        return {"validation_passed": True, "error": None, "detail": None, "fixed_text": None}

    result = logs[0].validation_result
    passed = "pass" in str(result.outcome).lower()
    message = getattr(result, "error_message", None)
    # The judge reports a transport failure through this metadata key. Surface it as an error
    # so it is visible, and keep the check itself as passed.
    judge_error = (result.metadata or {}).get("judge_error") if passed else None

    # A `fix` validator returns the repaired text, either as the corrected output of the parse
    # or as fix_value on the failure itself. Most validators carry neither field.
    fixed = getattr(result, "fix_value", None) or getattr(result, "value_override", None)
    corrected = getattr(outcome, "validated_output", None)
    if isinstance(corrected, str) and corrected != text:
        fixed = corrected

    return {
        "validation_passed": passed,
        "error": judge_error,
        "detail": None if passed else (str(message) if message else "blocked"),
        "fixed_text": fixed if isinstance(fixed, str) and fixed != text else None,
    }
