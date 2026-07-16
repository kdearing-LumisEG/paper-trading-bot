"""Integration tests for bundled session risk controls."""

import pandas as pd
import pytest

from trading_bot.backtest.engine import (
    BacktestError,
    run_backtest,
)
from trading_bot.backtest.risk_controls import (
    ConsecutiveLossLimit,
    DailyLossLimit,
    MaxTradesPerSession,
)
from trading_bot.backtest.risk_manager import (
    SessionRiskConfig,
)
from trading_bot.reporting.metrics import (
    PerformanceMetrics,
)


def make_three_trade_session() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["SPY"] * 7,
            "timestamp": pd.to_datetime(
                [
                    "2026-01-02T14:30:00Z",
                    "2026-01-02T14:45:00Z",
                    "2026-01-02T15:00:00Z",
                    "2026-01-02T15:15:00Z",
                    "2026-01-02T15:30:00Z",
                    "2026-01-02T15:45:00Z",
                    "2026-01-02T16:00:00Z",
                ],
                utc=True,
            ),
            "open": [100.0, 100.0, 99.0, 100.0, 98.0, 100.0, 101.0],
            "close": [100.0, 100.0, 99.0, 100.0, 98.0, 100.0, 101.0],
            "signal": [
                "enter_long",
                "exit_long",
                "enter_long",
                "exit_long",
                "enter_long",
                "exit_long",
                "hold",
            ],
        }
    )


def test_max_trades_per_session_blocks_third_entry() -> None:
    result = run_backtest(
        frame=make_three_trade_session(),
        session_risk=SessionRiskConfig(
            max_trades_per_session=MaxTradesPerSession(2)
        ),
    )

    assert result.number_of_trades == 2
    assert result.number_of_skipped_entries == 1
    assert result.skipped_entries[0].reason == (
        "max_trades_per_session"
    )
    assert result.skipped_entries[0].session_trades_started == 2


def test_consecutive_loss_limit_blocks_third_entry() -> None:
    result = run_backtest(
        frame=make_three_trade_session(),
        session_risk=SessionRiskConfig(
            consecutive_loss_limit=ConsecutiveLossLimit(2)
        ),
    )

    assert result.number_of_trades == 2
    assert result.net_pnl == pytest.approx(-3.0)
    assert result.number_of_skipped_entries == 1
    assert result.skipped_entries[0].reason == (
        "consecutive_loss_limit"
    )
    assert (
        result.skipped_entries[0].session_consecutive_losses
        == 2
    )


def test_session_risk_resets_for_next_day() -> None:
    first = make_three_trade_session()
    second = pd.DataFrame(
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
            "signal": ["enter_long", "hold"],
        }
    )

    result = run_backtest(
        frame=pd.concat([first, second], ignore_index=True),
        session_risk=SessionRiskConfig(
            max_trades_per_session=MaxTradesPerSession(2),
            consecutive_loss_limit=ConsecutiveLossLimit(2),
        ),
    )

    assert result.number_of_trades == 3
    assert result.number_of_skipped_entries == 1
    assert result.trades[-1].entry_time == pd.Timestamp(
        "2026-01-05T14:45:00Z"
    )


def test_daily_loss_legacy_argument_remains_supported() -> None:
    result = run_backtest(
        frame=make_three_trade_session(),
        daily_loss_limit=DailyLossLimit(1.0),
    )

    assert result.number_of_trades == 1
    assert result.number_of_skipped_entries == 2
    assert all(
        entry.reason == "daily_loss_limit"
        for entry in result.skipped_entries
    )


def test_legacy_and_new_risk_arguments_cannot_be_mixed() -> None:
    with pytest.raises(
        BacktestError,
        match="either session_risk or daily_loss_limit",
    ):
        run_backtest(
            frame=make_three_trade_session(),
            daily_loss_limit=DailyLossLimit(1.0),
            session_risk=SessionRiskConfig(),
        )


def test_metrics_include_risk_settings_and_rejection_counts() -> None:
    result = run_backtest(
        frame=make_three_trade_session(),
        session_risk=SessionRiskConfig(
            max_trades_per_session=MaxTradesPerSession(2)
        ),
    )

    metrics = PerformanceMetrics.from_backtest_result(result)
    summary = metrics.to_dict()

    assert summary["skipped_entries_by_reason"] == {
        "max_trades_per_session": 1
    }
    assert summary["risk_control_settings"] == {
        "daily_loss_limit": None,
        "max_trades_per_session": 2,
        "max_consecutive_losses_per_session": None,
    }


def test_skipped_entry_frame_contains_risk_snapshot() -> None:
    result = run_backtest(
        frame=make_three_trade_session(),
        session_risk=SessionRiskConfig(
            max_trades_per_session=MaxTradesPerSession(2)
        ),
    )

    frame = result.skipped_entries_to_frame()

    assert frame.loc[0, "session_date"] == "2026-01-02"
    assert frame.loc[0, "session_trades_started"] == 2
    assert frame.loc[0, "session_consecutive_losses"] == 2
