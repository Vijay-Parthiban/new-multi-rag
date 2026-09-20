"""Knowledge Product sync scheduling rules.

Plain sync pytest with bare asserts, matching the style of the other test files
in this directory. No fixtures, no async: both functions under test are pure.
"""

import pytest

from apps.api.routes.knowledge_products import _apply_schedule
from src.ingestion_service.core.knowledge_sync import (
    DEFAULT_INTERVAL_SECONDS,
    LIVE_INTERVAL_SECONDS,
    MIN_INTERVAL_SECONDS,
    resolved_interval_seconds,
)
from src.shared.db.models import KnowledgeProduct, SourceMonitorMode


def _product(mode: SourceMonitorMode, seconds: int | None = None, minutes: int | None = None) -> KnowledgeProduct:
    return KnowledgeProduct(
        name="t",
        monitor_mode=mode,
        sync_interval_seconds=seconds,
        sync_interval_minutes=minutes,
    )


def test_live_mode_polls_every_three_seconds() -> None:
    product = _product(SourceMonitorMode.LIVE, seconds=600)
    assert resolved_interval_seconds(product) == LIVE_INTERVAL_SECONDS == 3


def test_scheduled_interval_uses_seconds_then_minutes() -> None:
    assert resolved_interval_seconds(_product(SourceMonitorMode.SCHEDULED, seconds=30)) == 30
    assert resolved_interval_seconds(_product(SourceMonitorMode.SCHEDULED, minutes=5)) == 300
    assert resolved_interval_seconds(_product(SourceMonitorMode.SCHEDULED)) == DEFAULT_INTERVAL_SECONDS


def test_scheduled_interval_has_a_five_second_floor() -> None:
    assert MIN_INTERVAL_SECONDS == 5
    assert resolved_interval_seconds(_product(SourceMonitorMode.SCHEDULED, seconds=1)) == 5
    # Zero is treated as unset, so the default applies instead of the floor.
    assert resolved_interval_seconds(_product(SourceMonitorMode.SCHEDULED, minutes=0)) == DEFAULT_INTERVAL_SECONDS


def test_live_mode_clears_both_intervals() -> None:
    assert _apply_schedule(
        mode_in="live",
        seconds_in=30,
        minutes_in=None,
        current_mode="scheduled",
        current_seconds=None,
        current_minutes=10,
    ) == ("live", None, None)


def test_scheduled_seconds_clears_minutes_and_the_reverse() -> None:
    assert _apply_schedule(
        mode_in=None,
        seconds_in=45,
        minutes_in=None,
        current_mode="scheduled",
        current_seconds=None,
        current_minutes=10,
    ) == ("scheduled", 45, None)
    assert _apply_schedule(
        mode_in=None,
        seconds_in=None,
        minutes_in=15,
        current_mode="scheduled",
        current_seconds=45,
        current_minutes=None,
    ) == ("scheduled", None, 15)


def test_scheduled_without_any_interval_is_rejected() -> None:
    with pytest.raises(ValueError, match="INTERVAL_REQUIRED"):
        _apply_schedule(
            mode_in="scheduled",
            seconds_in=None,
            minutes_in=None,
            current_mode="scheduled",
            current_seconds=None,
            current_minutes=None,
        )


def test_scheduled_keeps_the_stored_interval_when_none_is_sent() -> None:
    assert _apply_schedule(
        mode_in=None,
        seconds_in=None,
        minutes_in=None,
        current_mode="scheduled",
        current_seconds=None,
        current_minutes=10,
    ) == ("scheduled", None, 10)
