"""Frozen development and unseen-evaluation period support."""

from dataclasses import dataclass
from datetime import date

import pandas as pd

from trading_bot.backtest.engine import run_backtest
from trading_bot.backtest.models import BacktestResult
from trading_bot.reporting.metrics import PerformanceMetrics
from trading_bot.strategies.indicators import (
    add_ema_indicators,
)
from trading_bot.strategies.signals import (
    add_crossover_signals,
)


FROZEN_STRATEGY_NAME = "ema_crossover_9_21"
FROZEN_FAST_PERIOD = 9
FROZEN_SLOW_PERIOD = 21
FROZEN_STARTING_CASH = 10_000.0


class PeriodEvaluationError(ValueError):
    """Raised when a research period cannot be evaluated."""


@dataclass(frozen=True)
class EvaluationPeriod:
    """Inclusive exchange-session dates for one research period."""

    name: str
    start_date: date
    end_date: date

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise PeriodEvaluationError(
                "Period name cannot be empty."
            )

        if self.start_date > self.end_date:
            raise PeriodEvaluationError(
                "Period start date cannot be after its end date."
            )


DEVELOPMENT_PERIOD = EvaluationPeriod(
    name="development",
    start_date=date(2024, 1, 1),
    end_date=date(2025, 6, 30),
)

UNSEEN_EVALUATION_PERIOD = EvaluationPeriod(
    name="unseen_evaluation",
    start_date=date(2025, 7, 1),
    end_date=date(2026, 6, 30),
)


@dataclass(frozen=True)
class PeriodEvaluation:
    """Strategy inputs and results for one frozen research period."""

    period: EvaluationPeriod
    strategy_frame: pd.DataFrame
    backtest_result: BacktestResult
    metrics: PerformanceMetrics

    @property
    def row_count(self) -> int:
        """Return the number of bars evaluated."""

        return len(self.strategy_frame)

    @property
    def first_timestamp(self) -> pd.Timestamp:
        """Return the first timestamp in the evaluated period."""

        return pd.Timestamp(
            self.strategy_frame["timestamp"].iloc[0]
        )

    @property
    def last_timestamp(self) -> pd.Timestamp:
        """Return the last timestamp in the evaluated period."""

        return pd.Timestamp(
            self.strategy_frame["timestamp"].iloc[-1]
        )


def select_period_bars(
    frame: pd.DataFrame,
    period: EvaluationPeriod,
) -> pd.DataFrame:
    """Select bars using inclusive New York exchange-session dates."""

    if frame.empty:
        raise PeriodEvaluationError(
            "Source bar data cannot be empty."
        )

    if "timestamp" not in frame.columns:
        raise PeriodEvaluationError(
            "Source bar data must include a timestamp column."
        )

    result = frame.copy(deep=True)

    try:
        result["timestamp"] = pd.to_datetime(
            result["timestamp"],
            utc=True,
            errors="raise",
        )
    except (TypeError, ValueError) as exc:
        raise PeriodEvaluationError(
            "Timestamp conversion failed."
        ) from exc

    if result["timestamp"].isna().any():
        raise PeriodEvaluationError(
            "Timestamp values cannot be null."
        )

    if result["timestamp"].duplicated().any():
        raise PeriodEvaluationError(
            "Duplicate timestamps cannot be evaluated."
        )

    if not result["timestamp"].is_monotonic_increasing:
        raise PeriodEvaluationError(
            "Bars must be ordered by timestamp."
        )

    session_dates = (
        result["timestamp"]
        .dt.tz_convert("America/New_York")
        .dt.date
    )

    selected = result.loc[
        (session_dates >= period.start_date)
        & (session_dates <= period.end_date)
    ].reset_index(drop=True)

    if selected.empty:
        raise PeriodEvaluationError(
            f"No bars were found for period '{period.name}'."
        )

    return selected


def evaluate_frozen_strategy(
    frame: pd.DataFrame,
    period: EvaluationPeriod,
    symbol: str = "SPY",
) -> PeriodEvaluation:
    """Evaluate the unchanged 9/21 EMA strategy for one period.

    Period selection happens before indicator calculation. Therefore,
    EMA state cannot carry from the development period into the unseen
    evaluation period.
    """

    period_bars = select_period_bars(
        frame=frame,
        period=period,
    )

    indicator_bars = add_ema_indicators(
        frame=period_bars,
        fast_period=FROZEN_FAST_PERIOD,
        slow_period=FROZEN_SLOW_PERIOD,
    )

    strategy_bars = add_crossover_signals(
        indicator_bars
    )

    backtest_result = run_backtest(
        frame=strategy_bars,
        starting_cash=FROZEN_STARTING_CASH,
        symbol=symbol,
    )

    metrics = PerformanceMetrics.from_backtest_result(
        backtest_result
    )

    return PeriodEvaluation(
        period=period,
        strategy_frame=strategy_bars.copy(
            deep=True
        ),
        backtest_result=backtest_result,
        metrics=metrics,
    )