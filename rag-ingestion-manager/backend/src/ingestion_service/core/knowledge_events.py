"""In-process event bus for the Knowledge Product fanout.

The fanout publishes progress here and the SSE route replays it to the product
page. One process only: the fanout runs inside the API process, so an in-memory
bus is enough and no broker is needed.
"""

import asyncio
import logging
import uuid
from collections import deque
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

MAX_REPLAY = 200
QUEUE_MAXSIZE = 200

_EVENTS: dict[uuid.UUID, deque[dict[str, Any]]] = {}
_WAITERS: dict[uuid.UUID, set[asyncio.Queue]] = {}
_SEQ: dict[uuid.UUID, int] = {}


def publish(product_id: uuid.UUID, kind: str, **fields: Any) -> None:
    """Record an event and push it to every open stream for this product.

    Call this from the event loop only. The destination writers run in worker
    threads, so they must not call it directly.
    """
    if not isinstance(product_id, uuid.UUID):
        try:
            product_id = uuid.UUID(str(product_id))
        except (ValueError, AttributeError, TypeError):
            logger.warning("knowledge_event_bad_product_id value=%s", product_id)
            return

    seq = _SEQ.get(product_id, 0) + 1
    _SEQ[product_id] = seq
    event = {"seq": seq, "ts": datetime.now(UTC).isoformat(), "kind": kind, **fields}

    replay = _EVENTS.setdefault(product_id, deque(maxlen=MAX_REPLAY))
    replay.append(event)

    for queue in list(_WAITERS.get(product_id, ())):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            # Drop the oldest so the newest state still arrives.
            try:
                queue.get_nowait()
                queue.put_nowait(event)
            except Exception:
                pass


def subscribe(product_id: uuid.UUID) -> tuple[list[dict[str, Any]], asyncio.Queue]:
    """Return the replay buffer and a queue that receives every later event."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
    _WAITERS.setdefault(product_id, set()).add(queue)
    return list(_EVENTS.get(product_id, ())), queue


def unsubscribe(product_id: uuid.UUID, queue: asyncio.Queue) -> None:
    waiters = _WAITERS.get(product_id)
    if not waiters:
        return
    waiters.discard(queue)
    if not waiters:
        _WAITERS.pop(product_id, None)


def clear(product_id: uuid.UUID) -> None:
    """Forget a product's history. Called when the product is deleted."""
    _EVENTS.pop(product_id, None)
    _WAITERS.pop(product_id, None)
    _SEQ.pop(product_id, None)
