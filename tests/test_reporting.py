import json
from pathlib import Path

import pandas as pd
import pytest

from trading_bot.backtest.engine import run_backtest
from trading_bot.reporting.export import (
    export_equity_curve_csv,
    export_performance_summary_json,
    export_trade_log_csv,
)
from trading_bot.reporting.metrics import PerformanceMetrics


def sample_bars() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2026-01-05T14:30:00Z",
                    "2026-01-05T14:45:00Z",
                    "2026-01-05T15:00:00Z",
                    "2026-01-05T15:15:00Z",
                    "2026-01-05T15:30:00Z",
                ],
                utc=True,
            ),
            "open": [100.0, 101.0, 102.0, 103.0, 104.0],
            "close": [101.0, 102.0, 103.0, 104.0, 105.0],
            "signal": [
                "hold",
                "enter_long",
                "hold",
                "exit_long",
                "hold",
            ],
        }
    )


def test_backtest_returns_equity_curve() -> None:
    result = run_backtest(sample_bars())

    assert not result.equity_curve.empty
    assert list(result.equity_curve.columns) == [
        "timestamp",
        "open",
        "close",
        "cash",
        "position_quantity",
        "position_market_value",
        "equity",
        "is_exposed",
        "running_peak_equity",
        "drawdown",
    ]
    assert result.equity_curve["equity"].iloc[0] == result.starting_cash
    assert result.equity_curve["equity"].iloc[-1] == pytest.approx(result.ending_cash)


def test_performance_metrics_from_backtest_result() -> None:
    result = run_backtest(sample_bars())
    metrics = PerformanceMetrics.from_backtest_result(result)

    assert metrics.starting_cash == 10_000.0
    assert metrics.ending_cash == pytest.approx(10_002.0)
    assert metrics.gross_pnl == pytest.approx(2.0)
    assert metrics.total_return_pct == pytest.approx(0.02)
    assert metrics.number_of_trades == 1
    assert metrics.winning_trades == 1
    assert metrics.losing_trades == 0
    assert metrics.win_rate_pct == pytest.approx(100.0)
    assert metrics.maximum_drawdown_pct == pytest.approx(0.0)
    assert metrics.baseline_gross_pnl == pytest.approx(5.0)
    assert metrics.baseline_return_pct == pytest.approx(0.05)


def test_export_helpers_write_files(tmp_path: Path) -> None:
    result = run_backtest(sample_bars())
    metrics = PerformanceMetrics.from_backtest_result(result)

    trade_log_path = tmp_path / "trade_log.csv"
    equity_curve_path = tmp_path / "equity_curve.csv"
    summary_path = tmp_path / "performance_summary.json"

    returned_trade_path = export_trade_log_csv(result.to_frame(), trade_log_path)
    returned_equity_path = export_equity_curve_csv(result.equity_curve, equity_curve_path)
    returned_summary_path = export_performance_summary_json(metrics.to_dict(), summary_path)

    assert returned_trade_path.exists()
    assert returned_equity_path.exists()
    assert returned_summary_path.exists()

    loaded_trades = pd.read_csv(trade_log_path)
    loaded_equity = pd.read_csv(equity_curve_path)
    loaded_summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert "gross_pnl" in loaded_trades.columns
    assert "equity" in loaded_equity.columns
    assert loaded_summary["number_of_trades"] == 1
