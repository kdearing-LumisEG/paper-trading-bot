"""Tests for frozen research-period evaluation."""

from datetime import date

import pandas as pd
import pytest

from trading_bot.backtest.period_evaluation import (
    DEVELOPMENT_PERIOD,
    FROZEN_FAST_PERIOD,
    FROZEN_SLOW_PERIOD,
    UNSEEN_EVALUATION_PERIOD,
    EvaluationPeriod,
    PeriodEvaluationError,
    evaluate_frozen_strategy,
    select_period_bars,
)


def make_two_period_frame() -> pd.DataFrame:
    development_timestamps = pd.date_range(
        start="2025-06-30T13:30:00Z",
        periods=26,
        freq="15min",
    )

    evaluation_timestamps = pd.date_range(
        start="2025-07-01T13:30:00Z",
        periods=26,
        freq="15min",
    )

    timestamps = development_timestamps.append(
        evaluation_timestamps
    )

    closes = [
        100.0 + index * 0.1
        for index in range(26)
    ] + [
        200.0 + index * 0.1
        for index in range(26)
    ]

    return pd.DataFrame(
        {
            "symbol": ["SPY"] * 52,
            "timestamp": timestamps,
            "open": closes,
            "high": [
                close + 1.0
                for close in closes
            ],
            "low": [
                close - 1.0
                for close in closes
            ],
            "close": closes,
            "volume": [1000] * 52,
        }
    )


def test_frozen_period_boundaries() -> None:
    assert DEVELOPMENT_PERIOD == EvaluationPeriod(
        name="development",
        start_date=date(2024, 1, 1),
        end_date=date(2025, 6, 30),
    )

    assert UNSEEN_EVALUATION_PERIOD == EvaluationPeriod(
        name="unseen_evaluation",
        start_date=date(2025, 7, 1),
        end_date=date(2026, 6, 30),
    )

    assert FROZEN_FAST_PERIOD == 9
    assert FROZEN_SLOW_PERIOD == 21


def test_period_selection_does_not_cross_boundary() -> None:
    frame = make_two_period_frame()

    development = select_period_bars(
        frame=frame,
        period=DEVELOPMENT_PERIOD,
    )

    evaluation = select_period_bars(
        frame=frame,
        period=UNSEEN_EVALUATION_PERIOD,
    )

    assert len(development) == 26
    assert len(evaluation) == 26

    assert development[
        "timestamp"
    ].max() < evaluation["timestamp"].min()


def test_evaluation_restarts_ema_state() -> None:
    evaluation = evaluate_frozen_strategy(
        frame=make_two_period_frame(),
        period=UNSEEN_EVALUATION_PERIOD,
    )

    slow_ema = evaluation.strategy_frame[
        "ema_slow"
    ]

    assert slow_ema.iloc[:20].isna().all()
    assert pd.notna(slow_ema.iloc[20])

    assert evaluation.row_count == 26

    assert evaluation.first_timestamp == pd.Timestamp(
        "2025-07-01T13:30:00Z"
    )

    assert evaluation.last_timestamp == pd.Timestamp(
        "2025-07-01T19:45:00Z"
    )


def test_source_dataframe_is_not_modified() -> None:
    source = make_two_period_frame()
    source_copy = source.copy(deep=True)

    evaluate_frozen_strategy(
        frame=source,
        period=DEVELOPMENT_PERIOD,
    )

    pd.testing.assert_frame_equal(
        source,
        source_copy,
    )


def test_empty_selected_period_fails() -> None:
    unavailable_period = EvaluationPeriod(
        name="unavailable",
        start_date=date(2023, 1, 1),
        end_date=date(2023, 12, 31),
    )

    with pytest.raises(
        PeriodEvaluationError,
        match="No bars were found",
    ):
        select_period_bars(
            frame=make_two_period_frame(),
            period=unavailable_period,
        )