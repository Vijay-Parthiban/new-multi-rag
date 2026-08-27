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
from guardrails.hub import BanList, DetectPII, ToxicLanguage

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
