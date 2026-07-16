"""Tests for gross and net performance reporting."""

import pandas as pd
import pytest

from trading_bot.backtest.costs import (
    ExecutionCostModel,
)
from trading_bot.backtest.engine import (
    run_backtest,
)
from trading_bot.reporting.metrics import (
    PerformanceMetrics,
)


def make_profitable_trade_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["SPY"] * 3,
            "timestamp": pd.to_datetime(
                [
                    "2026-01-02T14:30:00Z",
                    "2026-01-02T14:45:00Z",
                    "2026-01-02T15:00:00Z",
                ],
                utc=True,
            ),
            "open": [
                100.0,
                100.0,
                110.0,
            ],
            "close": [
                100.0,
                105.0,
                110.0,
            ],
            "signal": [
                "enter_long",
                "exit_long",
                "hold",
            ],
        }
    )


def test_metrics_separate_gross_and_net_results() -> None:
    result = run_backtest(
        frame=make_profitable_trade_frame(),
        starting_cash=10_000.0,
        cost_model=ExecutionCostModel(
            commission_per_order=1.0,
            slippage_bps=10.0,
        ),
    )

    metrics = (
        PerformanceMetrics
        .from_backtest_result(result)
    )

    assert metrics.gross_pnl == pytest.approx(
        10.0
    )

    assert metrics.gross_return_pct == (
        pytest.approx(0.10)
    )

    assert metrics.total_commissions == (
        pytest.approx(2.0)
    )

    assert metrics.total_slippage_cost == (
        pytest.approx(0.21)
    )

    assert metrics.total_costs == pytest.approx(
        2.21
    )

    assert metrics.net_pnl == pytest.approx(
        7.79
    )

    assert metrics.total_return_pct == (
        pytest.approx(0.0779)
    )

    assert metrics.average_gross_trade_pnl == (
        pytest.approx(10.0)
    )

    assert metrics.average_trade_pnl == (
        pytest.approx(7.79)
    )

    assert metrics.winning_trades == 1
    assert metrics.losing_trades == 0


def test_zero_cost_metrics_match_gross_results() -> None:
    result = run_backtest(
        frame=make_profitable_trade_frame(),
        starting_cash=10_000.0,
    )

    metrics = (
        PerformanceMetrics
        .from_backtest_result(result)
    )

    assert metrics.total_costs == 0.0

    assert metrics.net_pnl == pytest.approx(
        metrics.gross_pnl
    )

    assert metrics.total_return_pct == (
        pytest.approx(
            metrics.gross_return_pct
        )
    )


def test_metric_dictionary_contains_cost_fields() -> None:
    result = run_backtest(
        frame=make_profitable_trade_frame(),
        cost_model=ExecutionCostModel(
            commission_per_order=1.0,
            slippage_bps=10.0,
        ),
    )

    summary = (
        PerformanceMetrics
        .from_backtest_result(result)
        .to_dict()
    )

    assert summary[
        "gross_return_pct"
    ] == pytest.approx(0.10)

    assert summary[
        "total_commissions"
    ] == pytest.approx(2.0)

    assert summary[
        "total_slippage_cost"
    ] == pytest.approx(0.21)

    assert summary[
        "total_costs"
    ] == pytest.approx(2.21)

    assert summary[
        "net_pnl"
    ] == pytest.approx(7.79)