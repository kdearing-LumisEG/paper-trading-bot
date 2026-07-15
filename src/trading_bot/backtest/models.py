"""Structured models for backtest trades and results."""

from dataclasses import dataclass
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


@dataclass(frozen=True)
class BacktestResult:
    trades: list[Trade]
    starting_cash: float
    ending_cash: float
    gross_pnl: float
    number_of_trades: int

    @classmethod
    def from_trades(
        cls,
        trades: Iterable[Trade],
        starting_cash: float,
    ) -> "BacktestResult":
        trades_list = list(trades)
        ending_cash = starting_cash + sum(t.gross_pnl for t in trades_list)
        gross_pnl = sum(t.gross_pnl for t in trades_list)

        return cls(
            trades=trades_list,
            starting_cash=starting_cash,
            ending_cash=ending_cash,
            gross_pnl=gross_pnl,
            number_of_trades=len(trades_list),
        )

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "symbol": trade.symbol,
                    "entry_signal_time": trade.entry_signal_time,
                    "entry_time": trade.entry_time,
                    "entry_price": trade.entry_price,
                    "exit_signal_time": trade.exit_signal_time,
                    "exit_time": trade.exit_time,
                    "exit_price": trade.exit_price,
                    "quantity": trade.quantity,
                    "exit_reason": trade.exit_reason,
                    "gross_pnl": trade.gross_pnl,
                    "return_pct": trade.return_pct,
                    "bars_held": trade.bars_held,
                }
                for trade in self.trades
            ]
        )
