"""Tests for position sizing inside the backtest engine."""

import pandas as pd
import pytest

from trading_bot.backtest.costs import (
    ExecutionCostModel,
)
from trading_bot.backtest.engine import (
    run_backtest,
)
from trading_bot.backtest.position_sizing import (
    PositionSizingModel,
)


def make_trade_frame() -> pd.DataFrame:
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
            "open": [100.0, 100.0, 110.0],
            "close": [100.0, 105.0, 110.0],
            "signal": [
                "enter_long",
                "exit_long",
                "hold",
            ],
        }
    )


def test_configured_quantity_scales_trade() -> None:
    result = run_backtest(
        frame=make_trade_frame(),
        starting_cash=10_000.0,
        position_sizing=PositionSizingModel(
            quantity=3
        ),
    )

    assert result.number_of_trades == 1
    assert result.trades[0].quantity == 3

    assert result.gross_pnl == pytest.approx(
        30.0
    )

    assert result.net_pnl == pytest.approx(
        30.0
    )

    assert result.ending_cash == pytest.approx(
        10_030.0
    )


def test_insufficient_cash_records_skip() -> None:
    result = run_backtest(
        frame=make_trade_frame(),
        starting_cash=50.0,
        position_sizing=PositionSizingModel(
            quantity=1
        ),
    )

    assert result.number_of_trades == 0

    assert result.number_of_skipped_entries == 1

    skipped = result.skipped_entries[0]

    assert skipped.requested_quantity == 1

    assert skipped.required_cash == pytest.approx(
        100.0
    )

    assert skipped.available_cash == pytest.approx(
        50.0
    )

    assert skipped.reason == (
        "insufficient_cash_or_allocation_limit"
    )

    assert result.ending_cash == pytest.approx(
        50.0
    )


def test_cash_fraction_can_reject_entry() -> None:
    result = run_backtest(
        frame=make_trade_frame(),
        starting_cash=1_000.0,
        position_sizing=PositionSizingModel(
            quantity=6,
            max_cash_fraction=0.50,
        ),
    )

    assert result.number_of_trades == 0
    assert result.number_of_skipped_entries == 1

    skipped = result.skipped_entries[0]

    assert skipped.required_cash == pytest.approx(
        600.0
    )

    assert skipped.max_cash_fraction == pytest.approx(
        0.50
    )


def test_costs_are_included_in_affordability() -> None:
    result = run_backtest(
        frame=make_trade_frame(),
        starting_cash=100.50,
        cost_model=ExecutionCostModel(
            commission_per_order=1.0,
            slippage_bps=10.0,
        ),
        position_sizing=PositionSizingModel(
            quantity=1
        ),
    )

    assert result.number_of_trades == 0
    assert result.number_of_skipped_entries == 1

    skipped = result.skipped_entries[0]

    assert skipped.adjusted_fill_price == (
        pytest.approx(100.10)
    )

    assert skipped.required_cash == pytest.approx(
        101.10
    )


def test_default_sizing_remains_one_share() -> None:
    result = run_backtest(
        frame=make_trade_frame(),
    )

    assert result.number_of_trades == 1
    assert result.trades[0].quantity == 1
    assert result.number_of_skipped_entries == 0


def test_skipped_entries_can_be_exported_to_frame() -> None:
    result = run_backtest(
        frame=make_trade_frame(),
        starting_cash=50.0,
    )

    frame = result.skipped_entries_to_frame()

    assert len(frame) == 1

    assert frame.loc[
        0,
        "reason",
    ] == "insufficient_cash_or_allocation_limit"