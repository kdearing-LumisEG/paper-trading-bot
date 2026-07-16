"""Tests for daily realized-loss controls in the engine."""

import pandas as pd
import pytest

from trading_bot.backtest.costs import (
    ExecutionCostModel,
)
from trading_bot.backtest.engine import (
    run_backtest,
)
from trading_bot.backtest.risk_controls import (
    DailyLossLimit,
)


def make_repeated_entry_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["SPY"] * 6,
            "timestamp": pd.to_datetime(
                [
                    "2026-01-02T14:30:00Z",
                    "2026-01-02T14:45:00Z",
                    "2026-01-02T15:00:00Z",
                    "2026-01-02T15:15:00Z",
                    "2026-01-02T15:30:00Z",
                    "2026-01-02T15:45:00Z",
                ],
                utc=True,
            ),
            "open": [
                100.0,
                100.0,
                90.0,
                95.0,
                96.0,
                97.0,
            ],
            "close": [
                100.0,
                100.0,
                90.0,
                95.0,
                96.0,
                97.0,
            ],
            "signal": [
                "enter_long",
                "exit_long",
                "enter_long",
                "hold",
                "hold",
                "hold",
            ],
        }
    )


def test_daily_loss_limit_blocks_later_entry() -> None:
    result = run_backtest(
        frame=make_repeated_entry_frame(),
        daily_loss_limit=DailyLossLimit(
            max_daily_loss=10.0
        ),
    )

    assert result.number_of_trades == 1
    assert result.net_pnl == pytest.approx(-10.0)
    assert result.number_of_skipped_entries == 1

    skipped = result.skipped_entries[0]

    assert skipped.reason == "daily_loss_limit"

    assert skipped.signal_time == pd.Timestamp(
        "2026-01-02T15:00:00Z"
    )

    assert skipped.execution_time == pd.Timestamp(
        "2026-01-02T15:15:00Z"
    )


def test_no_limit_allows_later_entry() -> None:
    result = run_backtest(
        frame=make_repeated_entry_frame(),
    )

    assert result.number_of_trades == 2
    assert result.number_of_skipped_entries == 0
    assert result.net_pnl == pytest.approx(-8.0)


def test_daily_limit_resets_next_session() -> None:
    first_session = make_repeated_entry_frame()

    next_session = pd.DataFrame(
        {
            "symbol": ["SPY"] * 2,
            "timestamp": pd.to_datetime(
                [
                    "2026-01-05T14:30:00Z",
                    "2026-01-05T14:45:00Z",
                ],
                utc=True,
            ),
            "open": [100.0, 100.0],
            "close": [100.0, 101.0],
            "signal": [
                "enter_long",
                "hold",
            ],
        }
    )

    frame = pd.concat(
        [
            first_session,
            next_session,
        ],
        ignore_index=True,
    )

    result = run_backtest(
        frame=frame,
        daily_loss_limit=DailyLossLimit(
            max_daily_loss=10.0
        ),
    )

    assert result.number_of_trades == 2
    assert result.number_of_skipped_entries == 1

    assert result.trades[-1].entry_time == pd.Timestamp(
        "2026-01-05T14:45:00Z"
    )


def test_limit_uses_net_realized_pnl() -> None:
    frame = pd.DataFrame(
        {
            "symbol": ["SPY"] * 4,
            "timestamp": pd.to_datetime(
                [
                    "2026-01-02T14:30:00Z",
                    "2026-01-02T14:45:00Z",
                    "2026-01-02T15:00:00Z",
                    "2026-01-02T15:15:00Z",
                ],
                utc=True,
            ),
            "open": [
                100.0,
                100.0,
                96.0,
                100.0,
            ],
            "close": [
                100.0,
                100.0,
                96.0,
                100.0,
            ],
            "signal": [
                "enter_long",
                "exit_long",
                "enter_long",
                "hold",
            ],
        }
    )

    result = run_backtest(
        frame=frame,
        cost_model=ExecutionCostModel(
            commission_per_order=1.0
        ),
        daily_loss_limit=DailyLossLimit(
            max_daily_loss=5.0
        ),
    )

    assert result.trades[0].gross_pnl == pytest.approx(
        -4.0
    )

    assert result.trades[0].net_pnl == pytest.approx(
        -6.0
    )

    assert result.number_of_skipped_entries == 1

    assert result.skipped_entries[
        0
    ].reason == "daily_loss_limit"
