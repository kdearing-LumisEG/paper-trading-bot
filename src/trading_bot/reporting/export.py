"""Export helpers for backtest results and reports."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def _ensure_directory(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _validate_overwrite(path: Path, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"File exists: {path}")


def _base_export_root(root: Path | None = None) -> Path:
    return root if root is not None else Path("logs/backtests")


def export_trade_log_csv(
    trades: pd.DataFrame,
    path: Path,
    overwrite: bool = False,
) -> Path:
    _ensure_directory(path)
    _validate_overwrite(path, overwrite)
    trades.to_csv(path, index=False)
    return path


def export_equity_curve_csv(
    equity_curve: pd.DataFrame,
    path: Path,
    overwrite: bool = False,
) -> Path:
    _ensure_directory(path)
    _validate_overwrite(path, overwrite)
    equity_curve.to_csv(path, index=False)
    return path


def export_performance_summary_json(
    summary: dict[str, object | None],
    path: Path,
    overwrite: bool = False,
) -> Path:
    _ensure_directory(path)
    _validate_overwrite(path, overwrite)

    with path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)

    return path


def export_backtest_report(
    trades: pd.DataFrame,
    equity_curve: pd.DataFrame,
    summary: dict[str, object | None],
    experiment_name: str,
    root: Path | None = None,
    overwrite: bool = False,
) -> dict[str, Path]:
    if not experiment_name or not experiment_name.strip():
        raise ValueError("experiment_name must be a non-empty string.")

    root_path = _base_export_root(root) / experiment_name
    trade_log_path = root_path / "trade_log.csv"
    equity_curve_path = root_path / "equity_curve.csv"
    summary_path = root_path / "performance_summary.json"

    return {
        "trade_log": export_trade_log_csv(trades, trade_log_path, overwrite=overwrite),
        "equity_curve": export_equity_curve_csv(equity_curve, equity_curve_path, overwrite=overwrite),
        "performance_summary": export_performance_summary_json(summary, summary_path, overwrite=overwrite),
    }
