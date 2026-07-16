"""Tests for cost-aware trade and result accounting."""

from datetime import datetime, timezone

import pytest

from trading_bot.backtest.models import (
    BacktestResult,
    Trade,
)


def make_trade(
    *,
    gross_pnl: float = 10.0,
    net_pnl: float | None = None,
    entry_commission: float = 0.0,
    exit_commission: float = 0.0,
    slippage_cost: float = 0.0,
    total_costs: float = 0.0,
) -> Trade:
    return Trade(
        symbol="SPY",
        entry_signal_time=datetime(
            2026,
            1,
            2,
            14,
            30,
            tzinfo=timezone.utc,
        ),
        entry_time=datetime(
            2026,
            1,
            2,
            14,
            45,
            tzinfo=timezone.utc,
        ),
        entry_reference_price=100.0,
        entry_price=100.10,
        entry_commission=entry_commission,
        exit_signal_time=datetime(
            2026,
            1,
            2,
            15,
            0,
            tzinfo=timezone.utc,
        ),
        exit_time=datetime(
            2026,
            1,
            2,
            15,
            15,
            tzinfo=timezone.utc,
        ),
        exit_reference_price=110.0,
        exit_price=109.89,
        exit_commission=exit_commission,
        quantity=1,
        exit_reason="signal",
        gross_pnl=gross_pnl,
        slippage_cost=slippage_cost,
        total_costs=total_costs,
        net_pnl=net_pnl,
        return_pct=0.0779,
        bars_held=2,
    )


def test_legacy_trade_uses_gross_pnl_as_net() -> None:
    trade = make_trade(
        gross_pnl=10.0,
        net_pnl=None,
    )

    result = BacktestResult.from_trades(
        trades=[trade],
        starting_cash=10_000.0,
    )

    assert result.gross_pnl == pytest.approx(
        10.0
    )

    assert result.net_pnl == pytest.approx(
        10.0
    )

    assert result.ending_cash == pytest.approx(
        10_010.0
    )


def test_result_aggregates_execution_costs() -> None:
    trade = make_trade(
        gross_pnl=10.0,
        net_pnl=7.79,
        entry_commission=1.0,
        exit_commission=1.0,
        slippage_cost=0.21,
        total_costs=2.21,
    )

    result = BacktestResult.from_trades(
        trades=[trade],
        starting_cash=10_000.0,
    )

    assert result.gross_pnl == pytest.approx(
        10.0
    )

    assert result.total_commissions == pytest.approx(
        2.0
    )

    assert result.total_slippage_cost == pytest.approx(
        0.21
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


def test_trade_frame_contains_cost_fields() -> None:
    result = BacktestResult.from_trades(
        trades=[
            make_trade(
                net_pnl=7.79,
                entry_commission=1.0,
                exit_commission=1.0,
                slippage_cost=0.21,
                total_costs=2.21,
            )
        ],
        starting_cash=10_000.0,
    )

    frame = result.to_frame()

    assert frame.loc[
        0,
        "entry_reference_price",
    ] == pytest.approx(100.0)

    assert frame.loc[
        0,
        "exit_reference_price",
    ] == pytest.approx(110.0)

    assert frame.loc[
        0,
        "total_costs",
    ] == pytest.approx(2.21)

    assert frame.loc[
        0,
        "net_pnl",
    ] == pytest.approx(7.79)