"""Tests for the frozen period-evaluation runner."""

import json
from pathlib import Path

import pandas as pd
import pytest

from trading_bot.backtest.run_period_evaluation import (
    DEFAULT_DATA_PATH,
    DEFAULT_OUTPUT_ROOT,
    build_comparison_summary,
    build_parser,
    run_frozen_period_evaluation,
)


def make_two_period_frame() -> pd.DataFrame:
    development_timestamps = pd.date_range(
        start="2025-06-30T13:30:00Z",
        periods=26,
        freq="15min",
    )

    evaluation_timestamps = pd.date_range(
        start="2025-07-01T13:30:00Z",
        periods=26,
        freq="15min",
    )

    timestamps = development_timestamps.append(
        evaluation_timestamps
    )

    development_closes = [
        100.0 + index * 0.1
        for index in range(26)
    ]

    evaluation_closes = [
        200.0 + index * 0.1
        for index in range(26)
    ]

    closes = (
        development_closes
        + evaluation_closes
    )

    return pd.DataFrame(
        {
            "symbol": ["SPY"] * 52,
            "timestamp": timestamps,
            "open": closes,
            "high": [
                close + 1.0
                for close in closes
            ],
            "low": [
                close - 1.0
                for close in closes
            ],
            "close": closes,
            "volume": [1000] * 52,
        }
    )


def test_runner_exports_separate_period_reports(
    tmp_path: Path,
) -> None:
    result = run_frozen_period_evaluation(
        frame=make_two_period_frame(),
        output_root=tmp_path,
    )

    assert result.comparison_path.exists()

    assert set(
        result.development_paths
    ) == {
        "trade_log",
        "equity_curve",
        "performance_summary",
        "skipped_entries",
    }

    assert set(
        result.evaluation_paths
    ) == {
        "trade_log",
        "equity_curve",
        "performance_summary",
        "skipped_entries",
    }

    all_report_paths = (
        list(
            result.development_paths.values()
        )
        + list(
            result.evaluation_paths.values()
        )
    )

    for path in all_report_paths:
        assert path.exists()


def test_comparison_records_frozen_protocol(
    tmp_path: Path,
) -> None:
    result = run_frozen_period_evaluation(
        frame=make_two_period_frame(),
        output_root=tmp_path,
    )

    comparison = json.loads(
        result.comparison_path.read_text(
            encoding="utf-8"
        )
    )

    protocol = comparison[
        "research_protocol"
    ]

    assert protocol["fast_ema_period"] == 9
    assert protocol["slow_ema_period"] == 21

    assert protocol[
        "parameters_frozen_before_evaluation"
    ] is True

    assert protocol[
        "indicators_calculated_separately"
    ] is True

    assert protocol[
        "costs_and_slippage_included"
    ] is False

    assert comparison[
        "development"
    ]["period_end_date"] == "2025-06-30"

    assert comparison[
        "unseen_evaluation"
    ]["period_start_date"] == "2025-07-01"


def test_existing_outputs_fail_without_overwrite(
    tmp_path: Path,
) -> None:
    frame = make_two_period_frame()

    run_frozen_period_evaluation(
        frame=frame,
        output_root=tmp_path,
    )

    with pytest.raises(
        FileExistsError,
        match="Output file already exists",
    ):
        run_frozen_period_evaluation(
            frame=frame,
            output_root=tmp_path,
        )


def test_overwrite_allows_repeated_run(
    tmp_path: Path,
) -> None:
    frame = make_two_period_frame()

    run_frozen_period_evaluation(
        frame=frame,
        output_root=tmp_path,
    )

    result = run_frozen_period_evaluation(
        frame=frame,
        output_root=tmp_path,
        overwrite=True,
    )

    assert result.comparison_path.exists()


def test_comparison_summary_is_serializable(
    tmp_path: Path,
) -> None:
    result = run_frozen_period_evaluation(
        frame=make_two_period_frame(),
        output_root=tmp_path,
    )

    summary = build_comparison_summary(
        development=result.development,
        unseen_evaluation=(
            result.unseen_evaluation
        ),
    )

    serialized = json.dumps(summary)

    assert "unseen_evaluation" in serialized


def test_parser_defaults() -> None:
    arguments = build_parser().parse_args([])

    assert arguments.data_path == (
        DEFAULT_DATA_PATH
    )

    assert arguments.output_root == (
        DEFAULT_OUTPUT_ROOT
    )

    assert arguments.symbol == "SPY"
    assert arguments.overwrite is False
    