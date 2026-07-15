"""Tests for EMA crossover signal generation."""

import pandas as pd
import pytest

from trading_bot.strategies.signals import (
    SignalGenerationError,
    add_crossover_signals,
)


def sample_indicators() -> pd.DataFrame:
    """Create indicator values containing one entry and one exit."""

    return pd.DataFrame(
        {
            "timestamp": pd.date_range(
                start="2026-01-05T14:30:00Z",
                periods=6,
                freq="15min",
            ),
            "ema_fast": [
                float("nan"),
                1.0,
                1.0,
                2.0,
                3.0,
                1.0,
            ],
            "ema_slow": [
                float("nan"),
                1.5,
                1.0,
                1.5,
                2.5,
                2.0,
            ],
        }
    )


def test_entry_and_exit_crossovers_are_detected() -> None:
    result = add_crossover_signals(
        sample_indicators()
    )

    assert result["signal"].tolist() == [
        "hold",
        "hold",
        "hold",
        "enter_long",
        "hold",
        "exit_long",
    ]

    assert result["entry_signal"].sum() == 1
    assert result["exit_signal"].sum() == 1


def test_warmup_rows_do_not_generate_signals() -> None:
    result = add_crossover_signals(
        sample_indicators()
    )

    assert not result.loc[0, "entry_signal"]
    assert not result.loc[0, "exit_signal"]
    assert result.loc[0, "signal"] == "hold"


def test_input_dataframe_is_not_modified() -> None:
    original = sample_indicators()
    original_copy = original.copy(deep=True)

    add_crossover_signals(original)

    pd.testing.assert_frame_equal(
        original,
        original_copy,
    )

    assert "signal" not in original.columns


def test_future_values_do_not_change_past_signals() -> None:
    original = sample_indicators()
    modified = sample_indicators()

    modified.loc[
        modified.index[-1],
        "ema_fast",
    ] = 1000.0

    original_result = add_crossover_signals(
        original
    )

    modified_result = add_crossover_signals(
        modified
    )

    pd.testing.assert_series_equal(
        original_result["signal"].iloc[:-1],
        modified_result["signal"].iloc[:-1],
    )


def test_missing_ema_column_fails() -> None:
    frame = sample_indicators().drop(
        columns=["ema_slow"]
    )

    with pytest.raises(
        SignalGenerationError,
        match="Missing required columns",
    ):
        add_crossover_signals(frame)


def test_unordered_rows_fail() -> None:
    frame = (
        sample_indicators()
        .iloc[::-1]
        .reset_index(drop=True)
    )

    with pytest.raises(
        SignalGenerationError,
        match="ordered by timestamp",
    ):
        add_crossover_signals(frame)


def test_duplicate_timestamps_fail() -> None:
    frame = pd.concat(
        [sample_indicators(), sample_indicators().iloc[[0]]],
        ignore_index=True,
    )

    with pytest.raises(
        SignalGenerationError,
        match="Duplicate timestamps",
    ):
        add_crossover_signals(frame)


def test_empty_input_fails() -> None:
    with pytest.raises(
        SignalGenerationError,
        match="cannot be empty",
    ):
        add_crossover_signals(pd.DataFrame())


def test_no_repeated_entry_signal_while_above() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range(
                start="2026-01-05T14:30:00Z",
                periods=5,
                freq="15min",
            ),
            "ema_fast": [float("nan"), 1.0, 2.0, 3.0, 4.0],
            "ema_slow": [float("nan"), 1.5, 1.5, 1.5, 1.5],
        }
    )

    result = add_crossover_signals(frame)

    assert result["entry_signal"].sum() == 1
    assert result["signal"].tolist() == [
        "hold",
        "hold",
        "enter_long",
        "hold",
        "hold",
    ]
