"""Tests for exchange-session coverage auditing."""

from datetime import datetime, timezone

import pandas as pd

from trading_bot.data.coverage import audit_session_coverage


def test_complete_regular_session_passes() -> None:
    timestamps = pd.date_range(
        start="2026-01-05T14:30:00Z",
        periods=26,
        freq="15min",
    )

    bars = pd.DataFrame({"timestamp": timestamps})

    audit = audit_session_coverage(
        bars,
        timeframe_minutes=15,
        start=datetime(
            2026,
            1,
            5,
            tzinfo=timezone.utc,
        ),
        end=datetime(
            2026,
            1,
            6,
            tzinfo=timezone.utc,
        ),
    )

    assert audit.is_complete
    assert audit.sessions.loc[0, "expected_bars"] == 26
    assert audit.sessions.loc[0, "actual_bars"] == 26
    assert audit.missing_timestamps.empty


def test_missing_bar_is_detected() -> None:
    timestamps = pd.date_range(
        start="2026-01-05T14:30:00Z",
        periods=26,
        freq="15min",
    ).delete(5)

    bars = pd.DataFrame({"timestamp": timestamps})

    audit = audit_session_coverage(
        bars,
        timeframe_minutes=15,
        start=datetime(
            2026,
            1,
            5,
            tzinfo=timezone.utc,
        ),
        end=datetime(
            2026,
            1,
            6,
            tzinfo=timezone.utc,
        ),
    )

    assert not audit.is_complete
    assert audit.sessions.loc[0, "missing_bars"] == 1
    assert len(audit.missing_timestamps) == 1


def test_early_close_uses_shorter_session() -> None:
    timestamps = pd.date_range(
        start="2026-11-27T14:30:00Z",
        periods=14,
        freq="15min",
    )

    bars = pd.DataFrame({"timestamp": timestamps})

    audit = audit_session_coverage(
        bars,
        timeframe_minutes=15,
        start=datetime(
            2026,
            11,
            27,
            tzinfo=timezone.utc,
        ),
        end=datetime(
            2026,
            11,
            28,
            tzinfo=timezone.utc,
        ),
    )

    assert audit.is_complete
    assert audit.sessions.loc[0, "expected_bars"] == 14
    assert audit.sessions.loc[0, "actual_bars"] == 14