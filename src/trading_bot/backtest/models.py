"""Structured models for backtest trades and results."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

import pandas as pd


@dataclass(frozen=True)
class Trade:
    symbol: str | None
    entry_signal_time: datetime
    entry_time: datetime
    entry_price: float
    exit_signal_time: datetime | None
    exit_time: datetime
    exit_price: float
    quantity: int
    exit_reason: str
    gross_pnl: float
    return_pct: float
    bars_held: int
    entry_reference_price: float | None = None
    exit_reference_price: float | None = None
    entry_commission: float = 0.0
    exit_commission: float = 0.0
    slippage_cost: float = 0.0
    total_costs: float = 0.0
    net_pnl: float | None = None

    @property
    def resolved_net_pnl(self) -> float:
        """Return net P&L, falling back to gross for legacy trades."""

        if self.net_pnl is None:
            return self.gross_pnl

        return self.net_pnl


@dataclass(frozen=True)
class BacktestResult:
    trades: list[Trade]
    starting_cash: float
    ending_cash: float
    gross_pnl: float
    number_of_trades: int
    equity_curve: pd.DataFrame = field(
        default_factory=pd.DataFrame
    )
    total_commissions: float = 0.0
    total_slippage_cost: float = 0.0
    total_costs: float = 0.0
    net_pnl: float = 0.0

    @classmethod
    def from_trades(
        cls,
        trades: Iterable[Trade],
        starting_cash: float,
        equity_curve: pd.DataFrame | None = None,
    ) -> "BacktestResult":
        trades_list = list(trades)

        gross_pnl = sum(
            trade.gross_pnl
            for trade in trades_list
        )

        total_commissions = sum(
            trade.entry_commission
            + trade.exit_commission
            for trade in trades_list
        )

        total_slippage_cost = sum(
            trade.slippage_cost
            for trade in trades_list
        )

        total_costs = (
            total_commissions
            + total_slippage_cost
        )

        net_pnl = sum(
            trade.resolved_net_pnl
            for trade in trades_list
        )

        ending_cash = starting_cash + net_pnl

        return cls(
            trades=trades_list,
            starting_cash=starting_cash,
            ending_cash=ending_cash,
            gross_pnl=gross_pnl,
            number_of_trades=len(trades_list),
            equity_curve=(
                equity_curve.copy(deep=True)
                if equity_curve is not None
                else pd.DataFrame()
            ),
            total_commissions=total_commissions,
            total_slippage_cost=(
                total_slippage_cost
            ),
            total_costs=total_costs,
            net_pnl=net_pnl,
        )

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "symbol": trade.symbol,
                    "entry_signal_time": (
                        trade.entry_signal_time
                    ),
                    "entry_time": trade.entry_time,
                    "entry_reference_price": (
                        trade.entry_reference_price
                    ),
                    "entry_price": trade.entry_price,
                    "entry_commission": (
                        trade.entry_commission
                    ),
                    "exit_signal_time": (
                        trade.exit_signal_time
                    ),
                    "exit_time": trade.exit_time,
                    "exit_reference_price": (
                        trade.exit_reference_price
                    ),
                    "exit_price": trade.exit_price,
                    "exit_commission": (
                        trade.exit_commission
                    ),
                    "quantity": trade.quantity,
                    "exit_reason": trade.exit_reason,
                    "gross_pnl": trade.gross_pnl,
                    "slippage_cost": (
                        trade.slippage_cost
                    ),
                    "total_costs": trade.total_costs,
                    "net_pnl": (
                        trade.resolved_net_pnl
                    ),
                    "return_pct": trade.return_pct,
                    "bars_held": trade.bars_held,
                }
                for trade in self.trades
            ]
        )