"""Performance metric calculations for backtest results."""

from dataclasses import dataclass

import pandas as pd

from trading_bot.backtest.models import BacktestResult


@dataclass(frozen=True)
class PerformanceMetrics:
    starting_cash: float
    ending_cash: float
    gross_pnl: float
    total_return_pct: float
    maximum_drawdown_pct: float | None
    number_of_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float | None
    average_trade_pnl: float | None
    average_winner: float | None
    average_loser: float | None
    largest_winner: float | None
    largest_loser: float | None
    profit_factor: float | None
    exposure_pct: float
    baseline_gross_pnl: float
    baseline_return_pct: float
    baseline_note: str

    @classmethod
    def from_backtest_result(
        cls,
        backtest_result: BacktestResult,
        equity_curve: pd.DataFrame | None = None,
    ) -> "PerformanceMetrics":
        equity_curve = equity_curve if equity_curve is not None else backtest_result.equity_curve
        trades = backtest_result.trades
        gross_pnl = backtest_result.gross_pnl
        number_of_trades = backtest_result.number_of_trades
        winning_trades = sum(1 for trade in trades if trade.gross_pnl > 0)
        losing_trades = sum(1 for trade in trades if trade.gross_pnl < 0)
        total_winning = sum(trade.gross_pnl for trade in trades if trade.gross_pnl > 0)
        total_losing = sum(trade.gross_pnl for trade in trades if trade.gross_pnl < 0)

        win_rate_pct = (
            winning_trades / number_of_trades * 100
            if number_of_trades > 0
            else None
        )

        average_trade_pnl = (
            gross_pnl / number_of_trades
            if number_of_trades > 0
            else None
        )

        average_winner = (
            total_winning / winning_trades
            if winning_trades > 0
            else None
        )

        average_loser = (
            total_losing / losing_trades
            if losing_trades > 0
            else None
        )

        largest_winner = (
            max((trade.gross_pnl for trade in trades if trade.gross_pnl > 0), default=None)
        )

        largest_loser = (
            min((trade.gross_pnl for trade in trades if trade.gross_pnl < 0), default=None)
        )

        profit_factor = (
            total_winning / abs(total_losing)
            if total_winning > 0 and total_losing < 0
            else None
        )

        equity = equity_curve["equity"]
        peak = equity.cummax()
        drawdown = (equity - peak) / peak
        maximum_drawdown_pct = (
            abs(drawdown.min()) * 100
            if not drawdown.empty
            else None
        )

        exposure_pct = (
            equity_curve["is_exposed"].sum() / len(equity_curve) * 100
            if len(equity_curve) > 0
            else 0.0
        )

        if len(equity_curve) > 0:
            first_open = equity_curve["open"].iloc[0]
            last_close = equity_curve["close"].iloc[-1]
            baseline_gross_pnl = last_close - first_open
            baseline_return_pct = baseline_gross_pnl / backtest_result.starting_cash * 100
        else:
            baseline_gross_pnl = 0.0
            baseline_return_pct = 0.0

        baseline_note = (
            "Baseline represents a one-share buy-and-hold position "
            "entered at the first bar open and exited at the final bar close. "
            "This baseline may hold overnight and is provided as a reference, "
            "not an apples-to-apples comparison with the strategy."
        )

        return cls(
            starting_cash=backtest_result.starting_cash,
            ending_cash=backtest_result.ending_cash,
            gross_pnl=gross_pnl,
            total_return_pct=(backtest_result.ending_cash - backtest_result.starting_cash) / backtest_result.starting_cash * 100,
            maximum_drawdown_pct=maximum_drawdown_pct,
            number_of_trades=number_of_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate_pct=win_rate_pct,
            average_trade_pnl=average_trade_pnl,
            average_winner=average_winner,
            average_loser=average_loser,
            largest_winner=largest_winner,
            largest_loser=largest_loser,
            profit_factor=profit_factor,
            exposure_pct=exposure_pct,
            baseline_gross_pnl=baseline_gross_pnl,
            baseline_return_pct=baseline_return_pct,
            baseline_note=baseline_note,
        )

    def to_dict(self) -> dict[str, object | None]:
        return {
            "starting_cash": self.starting_cash,
            "ending_cash": self.ending_cash,
            "gross_pnl": self.gross_pnl,
            "total_return_pct": self.total_return_pct,
            "maximum_drawdown_pct": self.maximum_drawdown_pct,
            "number_of_trades": self.number_of_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate_pct": self.win_rate_pct,
            "average_trade_pnl": self.average_trade_pnl,
            "average_winner": self.average_winner,
            "average_loser": self.average_loser,
            "largest_winner": self.largest_winner,
            "largest_loser": self.largest_loser,
            "profit_factor": self.profit_factor,
            "exposure_pct": self.exposure_pct,
            "baseline_gross_pnl": self.baseline_gross_pnl,
            "baseline_return_pct": self.baseline_return_pct,
            "baseline_note": self.baseline_note,
        }
