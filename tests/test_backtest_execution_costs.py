"""Tests for execution costs inside the backtest engine."""

import pandas as pd
import pytest

from trading_bot.backtest.costs import (
    ExecutionCostModel,
)
from trading_bot.backtest.engine import (
    run_backtest,
)


def make_signal_exit_frame() -> pd.DataFrame:
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


def test_signal_trade_applies_costs() -> None:
    result = run_backtest(
        frame=make_signal_exit_frame(),
        starting_cash=10_000.0,
        cost_model=ExecutionCostModel(
            commission_per_order=1.0,
            slippage_bps=10.0,
        ),
    )

    assert result.number_of_trades == 1

    trade = result.trades[0]

    assert trade.entry_reference_price == (
        pytest.approx(100.0)
    )

    assert trade.entry_price == pytest.approx(
        100.10
    )

    assert trade.exit_reference_price == (
        pytest.approx(110.0)
    )

    assert trade.exit_price == pytest.approx(
        109.89
    )

    assert trade.gross_pnl == pytest.approx(
        10.0
    )

    assert trade.slippage_cost == (
        pytest.approx(0.21)
    )

    assert trade.total_costs == pytest.approx(
        2.21
    )

    assert trade.net_pnl == pytest.approx(
        7.79
    )

    assert result.total_commissions == (
        pytest.approx(2.0)
    )

    assert result.total_slippage_cost == (
        pytest.approx(0.21)
    )

    assert result.total_costs == pytest.approx(
        2.21
    )

    assert result.net_pnl == pytest.approx(
        7.79
    )

    assert result.ending_cash == pytest.approx(
        10_007.79
    )


def test_zero_cost_model_preserves_gross_result() -> None:
    result = run_backtest(
        frame=make_signal_exit_frame(),
        starting_cash=10_000.0,
    )

    trade = result.trades[0]

    assert trade.gross_pnl == pytest.approx(
        10.0
    )

    assert trade.total_costs == pytest.approx(
        0.0
    )

    assert trade.net_pnl == pytest.approx(
        10.0
    )

    assert result.ending_cash == pytest.approx(
        10_010.0
    )


def test_session_close_exit_applies_costs() -> None:
    frame = pd.DataFrame(
        {
            "symbol": ["SPY"] * 2,
            "timestamp": pd.to_datetime(
                [
                    "2026-01-02T14:30:00Z",
                    "2026-01-02T14:45:00Z",
                ],
                utc=True,
            ),
            "open": [100.0, 100.0],
            "close": [100.0, 105.0],
            "signal": [
                "enter_long",
                "hold",
            ],
        }
    )

    result = run_backtest(
        frame=frame,
        starting_cash=10_000.0,
        cost_model=ExecutionCostModel(
            commission_per_order=1.0,
            slippage_bps=10.0,
        ),
    )

    trade = result.trades[0]

    assert trade.exit_reason == "session_close"

    assert trade.gross_pnl == pytest.approx(
        5.0
    )

    assert trade.slippage_cost == pytest.approx(
        0.205
    )

    assert trade.total_costs == pytest.approx(
        2.205
    )

    assert trade.net_pnl == pytest.approx(
        2.795
    )

    assert result.ending_cash == pytest.approx(
        10_002.795
    )

    final_curve_row = result.equity_curve.iloc[-1]

    assert final_curve_row[
        "cash"
    ] == pytest.approx(
        9_898.90
    )

    assert final_curve_row[
        "position_quantity"
    ] == 1

    assert final_curve_row[
        "position_market_value"
    ] == pytest.approx(
        105.0
    )

    assert final_curve_row[
        "equity"
    ] == pytest.approx(
        10_003.90
    )