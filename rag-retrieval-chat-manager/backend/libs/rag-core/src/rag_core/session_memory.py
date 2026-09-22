"""Session-scoped conversation memory on Redis.

One session is one Redis LIST at ``{prefix}:memory:{session_id}``. ``RPUSH`` appends
a turn, ``LTRIM`` keeps only the newest entries, and every write refreshes the TTL.
An idle session therefore expires on its own, and ending a session is a single
``DEL``.

This is deliberately not the ``cache_redisvl`` namespace. That destination holds
chunk payloads for retrieval; mixing conversation state into it would put two
different lifetimes behind one prefix and make the purge path ambiguous.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence

from rag_shared.config import Settings

from rag_core.schemas import SessionTurn

logger = logging.getLogger(__name__)

# Ten exchanges is roughly the point where an answer stops being about the
# session and starts being about the transcript.
DEFAULT_MAX_TURNS = 10
DEFAULT_TTL_S = 86400

# One Redis client per URL. The pool is what makes this cheap; building a client
# per request would open a connection per chat turn.
_CLIENTS: dict[str, object] = {}


def _client(url: str):
    existing = _CLIENTS.get(url)
    if existing is not None:
        return existing
    import redis

    client = redis.Redis.from_url(url, decode_responses=True)
    _CLIENTS[url] = client
    return client


def memory_key(prefix: str, session_id: str) -> str:
    """The Redis key holding one session."""
    return f"{prefix}:memory:{session_id}"


class SessionMemoryUnavailable(RuntimeError):
    """Redis refused the operation. Only `clear` raises this."""


class SessionMemory:
    """Read and write the remembered turns of a session.

    Every method fails soft. A Redis outage makes the assistant stateless for the
    duration; it does not fail the chat turn, because losing conversation context
    is better than losing the answer.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        prefix: str,
        max_turns: int = DEFAULT_MAX_TURNS,
        ttl_s: int = DEFAULT_TTL_S,
    ) -> None:
        self._url = settings.redis_url
        self._prefix = prefix
        self._max_messages = max(2, max_turns * 2)
        self._ttl_s = max(60, ttl_s)

    @property
    def prefix(self) -> str:
        return self._prefix

    def key_for(self, session_id: str) -> str:
        return memory_key(self._prefix, session_id)

    def load(self, session_id: str) -> list[SessionTurn]:
        """The remembered turns, oldest first. Empty on any failure."""
        try:
            raw = _client(self._url).lrange(self.key_for(session_id), 0, -1)
        except Exception as exc:  # noqa: BLE001 - a memory miss must not fail a chat turn
            logger.warning("session memory read failed session=%s error=%s", session_id, exc)
            return []
        return [turn for turn in (self._decode(entry) for entry in raw) if turn is not None]

    def append(self, session_id: str, turns: Sequence[SessionTurn]) -> None:
        """Append the turns of one exchange and refresh the TTL."""
        payload = [json.dumps({"role": t.role, "content": t.content}) for t in turns if t.content]
        if not payload:
            return
        key = self.key_for(session_id)
        try:
            pipe = _client(self._url).pipeline()
            pipe.rpush(key, *payload)
            pipe.ltrim(key, -self._max_messages, -1)
            pipe.expire(key, self._ttl_s)
            pipe.execute()
        except Exception as exc:  # noqa: BLE001
            logger.warning("session memory write failed session=%s error=%s", session_id, exc)

    def clear(self, session_id: str) -> bool:
        """Delete the session. Returns True when a key was removed.

        A missing key is not an error: ending a session twice, or ending one that
        already expired, is a normal thing for a client to do.
        """
        try:
            return bool(_client(self._url).delete(self.key_for(session_id)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("session memory clear failed session=%s error=%s", session_id, exc)
            raise SessionMemoryUnavailable(str(exc)) from exc

    def inspect(self, session_id: str) -> dict:
        """What a caller may read back about a live session."""
        turns = self.load(session_id)
        ttl = -2
        try:
            ttl = _client(self._url).ttl(self.key_for(session_id))
        except Exception:  # noqa: BLE001
            pass
        return {
            "session_id": session_id,
            "exists": bool(turns),
            "turns": len(turns),
            # -1 means the key exists without an expiry, -2 means it is gone.
            "ttl_seconds": ttl if ttl >= 0 else None,
            "history": [t.model_dump() for t in turns],
        }

    @staticmethod
    def _decode(entry: str) -> SessionTurn | None:
        try:
            payload = json.loads(entry)
        except (TypeError, ValueError):
            return None
        role = payload.get("role")
        content = payload.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            return None
        return SessionTurn(role=role, content=content)
