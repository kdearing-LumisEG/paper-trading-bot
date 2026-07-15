"""Tests for deterministic technical indicators."""

import pandas as pd
import pytest

from trading_bot.strategies.indicators import (
    IndicatorCalculationError,
    add_ema_indicators,
)


def sample_bars() -> pd.DataFrame:
    """Create a small ordered close-price series."""

    closes = [
        10.0,
        11.0,
        12.0,
        13.0,
        14.0,
        15.0,
        16.0,
        17.0,
    ]

    return pd.DataFrame(
        {
            "timestamp": pd.date_range(
                start="2026-01-05T14:30:00Z",
                periods=len(closes),
                freq="15min",
            ),
            "close": closes,
        }
    )


def test_ema_values_and_warmup_periods() -> None:
    result = add_ema_indicators(
        sample_bars(),
        fast_period=3,
        slow_period=5,
    )

    assert result["ema_fast"].isna().sum() == 2
    assert result["ema_slow"].isna().sum() == 4

    assert result.loc[2, "ema_fast"] == pytest.approx(
        11.25
    )

    assert result.loc[4, "ema_slow"] == pytest.approx(
        12.3950617284
    )


def test_input_dataframe_is_not_modified() -> None:
    original = sample_bars()
    original_copy = original.copy(deep=True)

    add_ema_indicators(
        original,
        fast_period=3,
        slow_period=5,
    )

    pd.testing.assert_frame_equal(
        original,
        original_copy,
    )

    assert "ema_fast" not in original.columns
    assert "ema_slow" not in original.columns


def test_future_price_does_not_change_past_ema_values() -> None:
    original = sample_bars()
    modified = sample_bars()

    modified.loc[
        modified.index[-1],
        "close",
    ] = 1000.0

    original_result = add_ema_indicators(
        original,
        fast_period=3,
        slow_period=5,
    )

    modified_result = add_ema_indicators(
        modified,
        fast_period=3,
        slow_period=5,
    )

    pd.testing.assert_series_equal(
        original_result["ema_fast"].iloc[:-1],
        modified_result["ema_fast"].iloc[:-1],
    )

    pd.testing.assert_series_equal(
        original_result["ema_slow"].iloc[:-1],
        modified_result["ema_slow"].iloc[:-1],
    )

    assert (
        original_result["ema_fast"].iloc[-1]
        != modified_result["ema_fast"].iloc[-1]
    )


def test_unordered_bars_fail() -> None:
    bars = sample_bars().iloc[::-1].reset_index(
        drop=True
    )

    with pytest.raises(
        IndicatorCalculationError,
        match="ordered by timestamp",
    ):
        add_ema_indicators(
            bars,
            fast_period=3,
            slow_period=5,
        )


def test_invalid_periods_fail() -> None:
    with pytest.raises(
        IndicatorCalculationError,
        match="fast_period must be smaller",
    ):
        add_ema_indicators(
            sample_bars(),
            fast_period=5,
            slow_period=3,
        )
