"""Tests for processed market-bar state."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from trading_bot.runtime.signal_state import (
    JsonSignalStateStore,
)


def timestamp(
    hour: int,
    minute: int,
) -> datetime:
    return datetime(
        2026,
        1,
        2,
        hour,
        minute,
        tzinfo=timezone.utc,
    )


def test_signal_state_round_trip(
    tmp_path: Path,
) -> None:
    store = JsonSignalStateStore(
        tmp_path / "state.json"
    )

    store.mark_processed(
        strategy_name="ema_9_21",
        symbol="SPY",
        timeframe_minutes=15,
        bar_end=timestamp(15, 0),
        signal="enter_long",
        handled_at=timestamp(15, 1),
    )

    restored = JsonSignalStateStore(
        tmp_path / "state.json"
    )

    assert restored.is_processed(
        strategy_name="ema_9_21",
        symbol="SPY",
        timeframe_minutes=15,
        bar_end=timestamp(15, 0),
    )

    assert not restored.is_processed(
        strategy_name="ema_9_21",
        symbol="SPY",
        timeframe_minutes=15,
        bar_end=timestamp(15, 15),
    )


def test_older_bar_is_also_considered_processed(
    tmp_path: Path,
) -> None:
    store = JsonSignalStateStore(
        tmp_path / "state.json"
    )

    store.mark_processed(
        strategy_name="ema_9_21",
        symbol="SPY",
        timeframe_minutes=15,
        bar_end=timestamp(15, 15),
        signal="hold",
        handled_at=timestamp(15, 16),
    )

    assert store.is_processed(
        strategy_name="ema_9_21",
        symbol="SPY",
        timeframe_minutes=15,
        bar_end=timestamp(15, 0),
    )


def test_invalid_signal_state_fails(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.json"
    path.write_text(
        "not json",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="could not be read",
    ):
        JsonSignalStateStore(
            path
        ).is_processed(
            strategy_name="ema_9_21",
            symbol="SPY",
            timeframe_minutes=15,
            bar_end=timestamp(15, 0),
        )
