"""Run and export the frozen development and evaluation periods."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from trading_bot.backtest.period_evaluation import (
    DEVELOPMENT_PERIOD,
    FROZEN_FAST_PERIOD,
    FROZEN_SLOW_PERIOD,
    FROZEN_STARTING_CASH,
    FROZEN_STRATEGY_NAME,
    UNSEEN_EVALUATION_PERIOD,
    PeriodEvaluation,
    evaluate_frozen_strategy,
)
from trading_bot.data.storage import load_bars
from trading_bot.reporting.export import (
    export_backtest_report,
    export_performance_summary_json,
)


DEFAULT_DATA_PATH = Path(
    "data/processed/"
    "SPY_15min_2024-01-01_2026-06-30.parquet"
)

DEFAULT_OUTPUT_ROOT = Path(
    "logs/backtests/frozen_ema_9_21"
)


@dataclass(frozen=True)
class FrozenEvaluationRun:
    """Results and exported paths from one frozen evaluation run."""

    development: PeriodEvaluation
    unseen_evaluation: PeriodEvaluation
    development_paths: dict[str, Path]
    evaluation_paths: dict[str, Path]
    comparison_path: Path


def _period_summary(
    evaluation: PeriodEvaluation,
) -> dict[str, object]:
    """Build a serializable summary for one research period."""

    return {
        "period_name": evaluation.period.name,
        "period_start_date": (
            evaluation.period.start_date.isoformat()
        ),
        "period_end_date": (
            evaluation.period.end_date.isoformat()
        ),
        "row_count": evaluation.row_count,
        "first_timestamp": (
            evaluation.first_timestamp.isoformat()
        ),
        "last_timestamp": (
            evaluation.last_timestamp.isoformat()
        ),
        "strategy_name": FROZEN_STRATEGY_NAME,
        "fast_ema_period": FROZEN_FAST_PERIOD,
        "slow_ema_period": FROZEN_SLOW_PERIOD,
        "starting_cash": FROZEN_STARTING_CASH,
        "position_quantity": 1,
        "overnight_positions_allowed": False,
        "execution_assumption": "next_bar_open",
        "performance": evaluation.metrics.to_dict(),
    }


def build_comparison_summary(
    development: PeriodEvaluation,
    unseen_evaluation: PeriodEvaluation,
) -> dict[str, object]:
    """Build the frozen research-protocol comparison document."""

    return {
        "research_protocol": {
            "strategy_name": FROZEN_STRATEGY_NAME,
            "fast_ema_period": FROZEN_FAST_PERIOD,
            "slow_ema_period": FROZEN_SLOW_PERIOD,
            "starting_cash": FROZEN_STARTING_CASH,
            "position_quantity": 1,
            "execution_assumption": "next_bar_open",
            "overnight_positions_allowed": False,
            "periods_selected_before_evaluation": True,
            "parameters_frozen_before_evaluation": True,
            "indicators_calculated_separately": True,
            "costs_and_slippage_included": False,
        },
        "development": _period_summary(
            development
        ),
        "unseen_evaluation": _period_summary(
            unseen_evaluation
        ),
    }


def _expected_output_paths(
    output_root: Path,
) -> list[Path]:
    """Return every output path created by the runner."""

    report_names = [
        "trade_log.csv",
        "equity_curve.csv",
        "performance_summary.json",
        "skipped_entries.csv",
    ]

    paths = [
        output_root
        / DEVELOPMENT_PERIOD.name
        / name
        for name in report_names
    ]

    paths.extend(
        output_root
        / UNSEEN_EVALUATION_PERIOD.name
        / name
        for name in report_names
    )

    paths.append(
        output_root / "period_comparison.json"
    )

    return paths


def _validate_output_paths(
    output_root: Path,
    overwrite: bool,
) -> None:
    """Prevent a partial export when files already exist."""

    if overwrite:
        return

    existing_paths = [
        path
        for path in _expected_output_paths(
            output_root
        )
        if path.exists()
    ]

    if existing_paths:
        raise FileExistsError(
            f"Output file already exists: "
            f"{existing_paths[0]}"
        )


def run_frozen_period_evaluation(
    frame: pd.DataFrame,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    symbol: str = "SPY",
    overwrite: bool = False,
) -> FrozenEvaluationRun:
    """Run and export both frozen research periods."""

    _validate_output_paths(
        output_root=output_root,
        overwrite=overwrite,
    )

    development = evaluate_frozen_strategy(
        frame=frame,
        period=DEVELOPMENT_PERIOD,
        symbol=symbol,
    )

    unseen_evaluation = evaluate_frozen_strategy(
        frame=frame,
        period=UNSEEN_EVALUATION_PERIOD,
        symbol=symbol,
    )

    development_paths = export_backtest_report(
        trades=development.backtest_result.to_frame(),
        equity_curve=(
            development.backtest_result.equity_curve
        ),
        summary=_period_summary(
            development
        ),
        experiment_name=DEVELOPMENT_PERIOD.name,
        root=output_root,
        overwrite=overwrite,
        skipped_entries=(
            development
            .backtest_result
            .skipped_entries_to_frame()
        ),
    )

    evaluation_paths = export_backtest_report(
        trades=(
            unseen_evaluation
            .backtest_result
            .to_frame()
        ),
        equity_curve=(
            unseen_evaluation
            .backtest_result
            .equity_curve
        ),
        summary=_period_summary(
            unseen_evaluation
        ),
        experiment_name=(
            UNSEEN_EVALUATION_PERIOD.name
        ),
        root=output_root,
        overwrite=overwrite,
        skipped_entries=(
            unseen_evaluation
            .backtest_result
            .skipped_entries_to_frame()
        ),
    )

    comparison_path = (
        output_root
        / "period_comparison.json"
    )

    export_performance_summary_json(
        summary=build_comparison_summary(
            development=development,
            unseen_evaluation=unseen_evaluation,
        ),
        path=comparison_path,
        overwrite=overwrite,
    )

    return FrozenEvaluationRun(
        development=development,
        unseen_evaluation=unseen_evaluation,
        development_paths=development_paths,
        evaluation_paths=evaluation_paths,
        comparison_path=comparison_path,
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the frozen-evaluation command-line parser."""

    parser = argparse.ArgumentParser(
        description=(
            "Run the frozen 9/21 EMA strategy over "
            "development and unseen evaluation periods."
        )
    )

    parser.add_argument(
        "--data-path",
        type=Path,
        default=DEFAULT_DATA_PATH,
        help=(
            "Path to the validated multi-year "
            "Parquet dataset."
        ),
    )

    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Directory for evaluation reports.",
    )

    parser.add_argument(
        "--symbol",
        default="SPY",
        help="Expected trading symbol.",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing evaluation reports.",
    )

    return parser


def _print_period_result(
    evaluation: PeriodEvaluation,
) -> None:
    """Print a concise summary for one period."""

    metrics = evaluation.metrics

    print()
    print(
        f"{evaluation.period.name}: "
        f"{evaluation.period.start_date} through "
        f"{evaluation.period.end_date}"
    )
    print(f"Bars: {evaluation.row_count}")
    print(
        f"Trades: {metrics.number_of_trades}"
    )
    print(
        f"Gross P&L: ${metrics.gross_pnl:.2f}"
    )
    print(
        "Total return: "
        f"{metrics.total_return_pct:.4f}%"
    )
    print(
        "Maximum drawdown: "
        f"{metrics.maximum_drawdown_pct:.4f}%"
        if metrics.maximum_drawdown_pct
        is not None
        else "Maximum drawdown: unavailable"
    )
    print(
        "Win rate: "
        f"{metrics.win_rate_pct:.2f}%"
        if metrics.win_rate_pct is not None
        else "Win rate: unavailable"
    )
    print(
        "Profit factor: "
        f"{metrics.profit_factor:.4f}"
        if metrics.profit_factor is not None
        else "Profit factor: unavailable"
    )
    print(
        f"Exposure: {metrics.exposure_pct:.2f}%"
    )


def main() -> None:
    """Run the frozen evaluation from the command line."""

    arguments = build_parser().parse_args()

    bars = load_bars(
        arguments.data_path
    )

    result = run_frozen_period_evaluation(
        frame=bars,
        output_root=arguments.output_root,
        symbol=arguments.symbol,
        overwrite=arguments.overwrite,
    )

    print(
        "Frozen period evaluation completed."
    )

    _print_period_result(
        result.development
    )

    _print_period_result(
        result.unseen_evaluation
    )

    print()
    print(
        f"Comparison report: "
        f"{result.comparison_path.resolve()}"
    )
    print(
        "The unseen evaluation period is now "
        "considered seen data."
    )


if __name__ == "__main__":
    main()