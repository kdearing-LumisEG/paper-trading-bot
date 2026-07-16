"""Performance metric calculations for backtest results."""

from dataclasses import dataclass

import pandas as pd

from trading_bot.backtest.models import BacktestResult


@dataclass(frozen=True)
class PerformanceMetrics:
    starting_cash: float
    ending_cash: float
    gross_pnl: float
    gross_return_pct: float
    total_commissions: float
    total_slippage_cost: float
    total_costs: float
    net_pnl: float
    total_return_pct: float
    maximum_drawdown_pct: float | None
    number_of_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float | None
    average_gross_trade_pnl: float | None
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
        curve = (
            equity_curve
            if equity_curve is not None
            else backtest_result.equity_curve
        )

        trades = backtest_result.trades
        gross_pnl = backtest_result.gross_pnl
        net_pnl = backtest_result.net_pnl
        number_of_trades = backtest_result.number_of_trades

        net_trade_pnls = [
            trade.resolved_net_pnl
            for trade in trades
        ]

        winning_trade_pnls = [
            pnl
            for pnl in net_trade_pnls
            if pnl > 0
        ]

        losing_trade_pnls = [
            pnl
            for pnl in net_trade_pnls
            if pnl < 0
        ]

        winning_trades = len(
            winning_trade_pnls
        )

        losing_trades = len(
            losing_trade_pnls
        )

        total_winning = sum(
            winning_trade_pnls
        )

        total_losing = sum(
            losing_trade_pnls
        )

        win_rate_pct = (
            winning_trades
            / number_of_trades
            * 100
            if number_of_trades > 0
            else None
        )

        average_gross_trade_pnl = (
            gross_pnl / number_of_trades
            if number_of_trades > 0
            else None
        )

        average_trade_pnl = (
            net_pnl / number_of_trades
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
            max(
                winning_trade_pnls,
                default=None,
            )
        )

        largest_loser = (
            min(
                losing_trade_pnls,
                default=None,
            )
        )

        profit_factor = (
            total_winning
            / abs(total_losing)
            if total_winning > 0
            and total_losing < 0
            else None
        )

        maximum_drawdown_pct: float | None

        if not curve.empty:
            equity = pd.to_numeric(
                curve["equity"],
                errors="raise",
            ).copy()

            # Include forced terminal liquidation costs in
            # reported account performance.
            equity.iloc[-1] = (
                backtest_result.ending_cash
            )

            peak = equity.cummax()

            drawdown = (
                equity - peak
            ) / peak

            maximum_drawdown_pct = (
                abs(drawdown.min()) * 100
            )
        else:
            maximum_drawdown_pct = None

        exposure_pct = (
            curve["is_exposed"].sum()
            / len(curve)
            * 100
            if len(curve) > 0
            else 0.0
        )

        if len(curve) > 0:
            first_open = float(
                curve["open"].iloc[0]
            )

            last_close = float(
                curve["close"].iloc[-1]
            )

            baseline_gross_pnl = (
                last_close - first_open
            )

            baseline_return_pct = (
                baseline_gross_pnl
                / backtest_result.starting_cash
                * 100
            )
        else:
            baseline_gross_pnl = 0.0
            baseline_return_pct = 0.0

        baseline_note = (
            "Baseline represents a one-share buy-and-hold "
            "position entered at the first bar open and exited "
            "at the final bar close. This baseline may hold "
            "overnight and is provided as a reference, not an "
            "apples-to-apples comparison with the strategy."
        )

        gross_return_pct = (
            gross_pnl
            / backtest_result.starting_cash
            * 100
        )

        total_return_pct = (
            net_pnl
            / backtest_result.starting_cash
            * 100
        )

        return cls(
            starting_cash=(
                backtest_result.starting_cash
            ),
            ending_cash=(
                backtest_result.ending_cash
            ),
            gross_pnl=gross_pnl,
            gross_return_pct=gross_return_pct,
            total_commissions=(
                backtest_result.total_commissions
            ),
            total_slippage_cost=(
                backtest_result.total_slippage_cost
            ),
            total_costs=(
                backtest_result.total_costs
            ),
            net_pnl=net_pnl,
            total_return_pct=total_return_pct,
            maximum_drawdown_pct=(
                maximum_drawdown_pct
            ),
            number_of_trades=number_of_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate_pct=win_rate_pct,
            average_gross_trade_pnl=(
                average_gross_trade_pnl
            ),
            average_trade_pnl=(
                average_trade_pnl
            ),
            average_winner=average_winner,
            average_loser=average_loser,
            largest_winner=largest_winner,
            largest_loser=largest_loser,
            profit_factor=profit_factor,
            exposure_pct=exposure_pct,
            baseline_gross_pnl=(
                baseline_gross_pnl
            ),
            baseline_return_pct=(
                baseline_return_pct
            ),
            baseline_note=baseline_note,
        )

    def to_dict(
        self,
    ) -> dict[str, object | None]:
        return {
            "starting_cash": self.starting_cash,
            "ending_cash": self.ending_cash,
            "gross_pnl": self.gross_pnl,
            "gross_return_pct": (
                self.gross_return_pct
            ),
            "total_commissions": (
                self.total_commissions
            ),
            "total_slippage_cost": (
                self.total_slippage_cost
            ),
            "total_costs": self.total_costs,
            "net_pnl": self.net_pnl,
            "total_return_pct": (
                self.total_return_pct
            ),
            "maximum_drawdown_pct": (
                self.maximum_drawdown_pct
            ),
            "number_of_trades": (
                self.number_of_trades
            ),
            "winning_trades": (
                self.winning_trades
            ),
            "losing_trades": (
                self.losing_trades
            ),
            "win_rate_pct": self.win_rate_pct,
            "average_gross_trade_pnl": (
                self.average_gross_trade_pnl
            ),
            "average_trade_pnl": (
                self.average_trade_pnl
            ),
            "average_winner": (
                self.average_winner
            ),
            "average_loser": (
                self.average_loser
            ),
            "largest_winner": (
                self.largest_winner
            ),
            "largest_loser": (
                self.largest_loser
            ),
            "profit_factor": (
                self.profit_factor
            ),
            "exposure_pct": self.exposure_pct,
            "baseline_gross_pnl": (
                self.baseline_gross_pnl
            ),
            "baseline_return_pct": (
                self.baseline_return_pct
            ),
            "baseline_note": (
                self.baseline_note
            ),
        }