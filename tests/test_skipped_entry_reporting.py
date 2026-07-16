"""Tests for skipped-entry metrics and exports."""

from pathlib import Path

import pandas as pd
import pytest

from trading_bot.backtest.engine import (
    run_backtest,
)
from trading_bot.reporting.export import (
    export_skipped_entries_csv,
)
from trading_bot.reporting.metrics import (
    PerformanceMetrics,
)


def make_rejected_entry_frame() -> pd.DataFrame:
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


def test_metrics_include_skipped_entry_count() -> None:
    result = run_backtest(
        frame=make_rejected_entry_frame(),
        starting_cash=50.0,
    )

    metrics = (
        PerformanceMetrics
        .from_backtest_result(result)
    )

    assert metrics.number_of_trades == 0
    assert metrics.number_of_skipped_entries == 1

    summary = metrics.to_dict()

    assert summary[
        "number_of_skipped_entries"
    ] == 1


def test_skipped_entries_export_to_csv(
    tmp_path: Path,
) -> None:
    result = run_backtest(
        frame=make_rejected_entry_frame(),
        starting_cash=50.0,
    )

    output_path = (
        tmp_path / "skipped_entries.csv"
    )

    returned_path = export_skipped_entries_csv(
        skipped_entries=(
            result.skipped_entries_to_frame()
        ),
        path=output_path,
    )

    assert returned_path == output_path
    assert output_path.exists()

    exported = pd.read_csv(output_path)

    assert len(exported) == 1

    assert exported.loc[
        0,
        "requested_quantity",
    ] == 1

    assert exported.loc[
        0,
        "required_cash",
    ] == pytest.approx(100.0)

    assert exported.loc[
        0,
        "reason",
    ] == "insufficient_cash_or_allocation_limit"


def test_skipped_export_protects_existing_file(
    tmp_path: Path,
) -> None:
    output_path = (
        tmp_path / "skipped_entries.csv"
    )

    skipped_entries = pd.DataFrame(
        {
            "reason": [
                "insufficient_cash"
            ]
        }
    )

    export_skipped_entries_csv(
        skipped_entries=skipped_entries,
        path=output_path,
    )

    with pytest.raises(
        FileExistsError,
        match="File exists",
    ):
        export_skipped_entries_csv(
            skipped_entries=skipped_entries,
            path=output_path,
        )