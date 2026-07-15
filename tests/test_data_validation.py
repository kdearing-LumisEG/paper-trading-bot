"""Tests for historical bar validation and storage."""

from pathlib import Path

import pandas as pd
import pytest

from trading_bot.data.storage import load_bars, save_bars
from trading_bot.data.validation import (
    BarValidationError,
    filter_regular_session_bars,
    validate_bars,
)


def sample_bars() -> pd.DataFrame:
    """Create valid but intentionally unordered SPY bars."""

    return pd.DataFrame(
        {
            "symbol": ["spy", "SPY", "SPY"],
            "timestamp": [
                "2026-01-05T15:00:00Z",
                "2026-01-05T14:30:00Z",
                "2026-01-05T14:45:00Z",
            ],
            "open": [602.0, 600.0, 601.0],
            "high": [603.0, 601.5, 602.5],
            "low": [601.5, 599.5, 600.5],
            "close": [602.5, 601.0, 602.0],
            "volume": [1200, 1000, 1100],
        }
    )


def test_valid_bars_are_normalized_and_sorted() -> None:
    result = validate_bars(
        sample_bars(),
        expected_symbol="SPY",
        timeframe_minutes=15,
    )

    assert result["symbol"].tolist() == [
        "SPY",
        "SPY",
        "SPY",
    ]

    assert result["timestamp"].is_monotonic_increasing
    assert pd.api.types.is_datetime64_any_dtype(
        result["timestamp"].dtype
    )
    assert str(result["timestamp"].dt.tz) == "UTC"


def test_duplicate_bars_fail() -> None:
    frame = sample_bars()
    frame.loc[1, "timestamp"] = frame.loc[0, "timestamp"]

    with pytest.raises(
        BarValidationError,
        match="Duplicate",
    ):
        validate_bars(
            frame,
            expected_symbol="SPY",
            timeframe_minutes=15,
        )


def test_impossible_high_price_fails() -> None:
    frame = sample_bars()
    frame.loc[0, "high"] = 500.0

    with pytest.raises(
        BarValidationError,
        match="high price",
    ):
        validate_bars(
            frame,
            expected_symbol="SPY",
            timeframe_minutes=15,
        )


def test_wrong_symbol_fails() -> None:
    frame = sample_bars()
    frame.loc[0, "symbol"] = "QQQ"

    with pytest.raises(
        BarValidationError,
        match="Expected only SPY",
    ):
        validate_bars(
            frame,
            expected_symbol="SPY",
            timeframe_minutes=15,
        )


def test_misaligned_timestamp_fails() -> None:
    frame = sample_bars()
    frame.loc[0, "timestamp"] = "2026-01-05T15:07:00Z"

    with pytest.raises(
        BarValidationError,
        match="not aligned",
    ):
        validate_bars(
            frame,
            expected_symbol="SPY",
            timeframe_minutes=15,
        )


def test_regular_session_filter_removes_outside_bars() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2026-01-05T14:15:00Z",
                    "2026-01-05T14:30:00Z",
                    "2026-01-05T20:45:00Z",
                    "2026-01-05T21:00:00Z",
                ],
                utc=True,
            )
        }
    )

    result = filter_regular_session_bars(frame)

    assert len(result) == 2
    assert result["timestamp"].tolist() == [
        pd.Timestamp("2026-01-05T14:30:00Z"),
        pd.Timestamp("2026-01-05T20:45:00Z"),
    ]


def test_parquet_round_trip(tmp_path: Path) -> None:
    validated = validate_bars(
        sample_bars(),
        expected_symbol="SPY",
        timeframe_minutes=15,
    )

    output_path = tmp_path / "bars.parquet"

    save_bars(validated, output_path)
    reloaded = load_bars(output_path)

    pd.testing.assert_frame_equal(
        validated,
        reloaded,
    )
