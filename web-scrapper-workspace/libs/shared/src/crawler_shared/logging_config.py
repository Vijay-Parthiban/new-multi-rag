from __future__ import annotations

import logging
import os


def setup_logging(*, default_level: str = "INFO") -> None:
    """Configure standard application logging.

    Why this exists:
    - We run the same code under API, worker, CLI, and tests.
    - We want consistent log formatting and a single env var (`LOG_LEVEL`)
      to change verbosity without code changes.

    Behavior:
    - Reads `LOG_LEVEL` from environment (defaults to `default_level`).
    - Uses a simple text format that works well in containers.
    """
    level_name = os.getenv("LOG_LEVEL", default_level).upper().strip()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
