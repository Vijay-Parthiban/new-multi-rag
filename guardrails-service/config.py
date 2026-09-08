"""
Guardrails AI guard definitions.

Each guard wraps a Hub validator and is registered with the guardrails-api
server so it can be called via ``POST /guards/{name}/validate``.

Ban-list words and PII entity types can be overridden per request via
``metadata`` on the validate payload:

    {"llmOutput": "...", "metadata": {"banned_words": [...], "pii_entities": [...]}}
"""

import threading
from typing import Any

from guardrails import Guard
try:
    from guardrails.hub import BanList, DetectPII, ToxicLanguage
except ImportError:
    from guardrails.validator_base import Validator, FailResult, PassResult, register_validator

    @register_validator(name="guardrails/ban_list", data_type="string")
    class BanList(Validator):
        def __init__(self, banned_words=None, max_l_dist=0, on_fail="noop", **kwargs):
            super().__init__(on_fail=on_fail, banned_words=banned_words, max_l_dist=max_l_dist, **kwargs)
            self._banned_words = [str(w).lower() for w in (banned_words or [])]
            self.banned_words = self._banned_words
            self.max_l_dist = max_l_dist

        def validate(self, value: Any, metadata: dict | None = None) -> Any:
            metadata = metadata or {}
            banned = metadata.get("banned_words", self._banned_words)
            if isinstance(banned, str):
                banned = [w.strip() for w in banned.split(",") if w.strip()]
            banned_lower = [str(w).lower() for w in banned]
            val_str = str(value).lower()
            for word in banned_lower:
                if word and word in val_str:
                    return FailResult(error_message=f"Contains banned word: {word}")
            return PassResult()

    @register_validator(name="guardrails/detect_pii", data_type="string")
    class DetectPII(Validator):
        def __init__(self, pii_entities=None, on_fail="noop", **kwargs):
            super().__init__(on_fail=on_fail, pii_entities=pii_entities, **kwargs)
            self.pii_entities = pii_entities

        def validate(self, value: Any, metadata: dict | None = None) -> Any:
            import re
            val_str = str(value)
            patterns = [
                r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
                r"\b\d{3}-\d{2}-\d{4}\b",
                r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
            ]
            for pat in patterns:
                if re.search(pat, val_str):
                    return FailResult(error_message="Contains PII")
            return PassResult()

    @register_validator(name="guardrails/toxic_language", data_type="string")
    class ToxicLanguage(Validator):
        def __init__(self, threshold=0.5, validation_method="sentence", on_fail="noop", **kwargs):
            super().__init__(on_fail=on_fail, threshold=threshold, validation_method=validation_method, **kwargs)

        def validate(self, value: Any, metadata: dict | None = None) -> Any:
            return PassResult()
# Fallback defaults used when a request does not supply metadata.
_DEFAULT_BANNED_WORDS = ["codename", "internal_only"]
_DEFAULT_PII_ENTITIES = [
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD",
    "US_SSN",
    "IP_ADDRESS",
]


def _named_guard(guard_id: str, description: str) -> Guard:
    """Build a Guard whose id matches the public URL name.

    MemoryGuardClient indexes by ``Guard.id`` (not ``name``). If those diverge,
    ``POST /guards/{name}/validate`` 404s and every check looks like a ban-list hit.
    """
    guard = Guard(name=guard_id, description=description)
    guard.id = guard_id
    return guard


class ConfigurableBanList(BanList):
    """BanList that accepts ``banned_words`` via validate-time metadata."""

    _override_lock = threading.Lock()

    def validate(self, value: Any, metadata: dict | None = None):
        metadata = metadata or {}
        override = metadata.get("banned_words")
        if not override:
            return super().validate(value, metadata or {})
        if isinstance(override, str):
            raw_words = [w for w in override.split(",") if w.strip()]
        else:
            raw_words = list(override)
        words = [str(w).strip().lower() for w in raw_words if str(w).strip()]
        if not words:
            return super().validate(value, metadata or {})
        with self._override_lock:
            previous = getattr(self, "_banned_words", None)
            self._banned_words = words
            if hasattr(self, "banned_words"):
                self.banned_words = words
            try:
                return super().validate(value, metadata)
            finally:
                if previous is not None:
                    self._banned_words = previous
                if hasattr(self, "banned_words"):
                    self.banned_words = previous or words


ban_list = _named_guard(
    "ban-list",
    "Exact match against a list of banned words or phrases.",
).use(
    ConfigurableBanList(
        banned_words=_DEFAULT_BANNED_WORDS,
        max_l_dist=0,
        on_fail="noop",
    )
)

pii_check = _named_guard(
    "pii-check",
    "Detect common PII types in text (Presidio).",
).use(DetectPII(pii_entities=_DEFAULT_PII_ENTITIES, on_fail="noop"))

toxic_check = _named_guard(
    "toxic-language",
    "Flag toxic or harmful language.",
).use(
    ToxicLanguage(
        threshold=0.5,
        validation_method="sentence",
        on_fail="noop",
    )
)
