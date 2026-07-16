import json
from pathlib import Path

import pandas as pd
import pytest

from trading_bot.backtest.engine import run_backtest
from trading_bot.reporting.export import export_backtest_report, export_equity_curve_csv, export_performance_summary_json, export_trade_log_csv
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


def bar_row_values() -> pd.DataFrame:
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
            "close": [100.0, 100.0, 100.0, 100.0, 100.0],
            "signal": [
                "hold",
                "enter_long",
                "hold",
                "hold",
                "hold",
            ],
        }
    )


def test_equity_equals_cash_plus_position_value() -> None:
    result = run_backtest(bar_row_values())

    equity_curve = result.equity_curve
    for _, row in equity_curve.iterrows():
        expected_equity = row["cash"] + row["position_quantity"] * row["close"]
        assert row["equity"] == pytest.approx(expected_equity)


def test_equity_changes_correctly_while_long() -> None:
    bars = pd.DataFrame(
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
            "close": [100.0, 101.0, 100.0, 102.0, 103.0],
            "signal": [
                "hold",
                "enter_long",
                "hold",
                "hold",
                "hold",
            ],
        }
    )
    result = run_backtest(bars)
    equity_curve = result.equity_curve

    assert equity_curve["is_exposed"].sum() > 0
    exposed_equity = equity_curve.loc[equity_curve["is_exposed"], "equity"]
    assert exposed_equity.iloc[0] != exposed_equity.iloc[-1]


def test_equity_accounting_transition_entry_and_exit() -> None:
    # Manual expectations:
    #  1. Start with 10,000 cash, 0 shares, equity 10,000.
    #  2. 'enter_long' on row 1 buys 1 share at row 2 open = 102.
    #  3. Cash drops by 102 to 9,898; equity becomes cash + close share value.
    #  4. While long, cash remains 9,898 and equity changes with close price.
    #  5. 'exit_long' on row 3 exits at row 4 open = 103; cash returns to 10,001.
    bars = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2026-01-05T14:30:00Z",
                    "2026-01-05T14:45:00Z",
                    "2026-01-05T15:00:00Z",
                    "2026-01-05T15:15:00Z",
                    "2026-01-05T15:30:00Z",
                    "2026-01-05T15:45:00Z",
                ],
                utc=True,
            ),
            "open": [100.0, 101.0, 102.0, 103.0, 103.0, 104.0],
            "close": [100.0, 101.0, 102.5, 102.2, 104.0, 104.5],
            "signal": [
                "hold",
                "enter_long",
                "hold",
                "hold",
                "exit_long",
                "hold",
            ],
        }
    )
    result = run_backtest(bars)
    curve = result.equity_curve

    assert curve.iloc[0]["cash"] == pytest.approx(10_000.0)
    assert curve.iloc[0]["position_quantity"] == 0
    assert curve.iloc[0]["equity"] == pytest.approx(10_000.0)

    assert curve.iloc[2]["cash"] == pytest.approx(9_898.0)
    assert curve.iloc[2]["position_quantity"] == 1
    assert curve.iloc[2]["position_market_value"] == pytest.approx(102.5)
    assert curve.iloc[2]["equity"] == pytest.approx(9_898.0 + 102.5)

    assert curve.iloc[3]["cash"] == pytest.approx(9_898.0)
    assert curve.iloc[3]["position_quantity"] == 1
    assert curve.iloc[3]["equity"] == pytest.approx(9_898.0 + 102.2)

    # Exit_long on row 4 exits at the next row open (row 5 open = 104).
    assert curve.iloc[4]["cash"] == pytest.approx(9_898.0)
    assert curve.iloc[4]["position_quantity"] == 1
    assert curve.iloc[4]["equity"] == pytest.approx(9_898.0 + 104.0)

    assert curve.iloc[5]["cash"] == pytest.approx(10_002.0)
    assert curve.iloc[5]["position_quantity"] == 0
    assert curve.iloc[5]["equity"] == pytest.approx(10_002.0)


def test_forced_session_close_realizes_mark_to_market_value() -> None:
    # Manual expectations:
    #  1. Enter at row 2 open = 101, leaving cash 9,899 and equity 10,001 when the share is worth 102.
    #  2. When the session changes on row 3, the position must force-close at row 2 close = 102.
    #  3. The row after the session boundary should show cash 10,000 and zero quantity.
    bars = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2026-01-05T19:00:00Z",
                    "2026-01-05T19:15:00Z",
                    "2026-01-05T19:30:00Z",
                    "2026-01-06T14:30:00Z",
                ],
                utc=True,
            ),
            "open": [100.0, 101.0, 101.0, 103.0],
            "close": [100.0, 101.0, 102.0, 103.0],
            "signal": [
                "hold",
                "enter_long",
                "hold",
                "hold",
            ],
        }
    )
    result = run_backtest(bars)
    curve = result.equity_curve

    assert curve.iloc[2]["cash"] == pytest.approx(9_899.0)
    assert curve.iloc[2]["position_quantity"] == 1
    assert curve.iloc[2]["position_market_value"] == pytest.approx(102.0)
    assert curve.iloc[2]["equity"] == pytest.approx(10_001.0)

    assert curve.iloc[3]["cash"] == pytest.approx(10_001.0)
    assert curve.iloc[3]["position_quantity"] == 0
    assert curve.iloc[3]["position_market_value"] == pytest.approx(0.0)
    assert curve.iloc[3]["equity"] == pytest.approx(10_001.0)


def test_drawdown_column_is_computed_from_equity_cummax() -> None:
    bars = pd.DataFrame(
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
            "open": [100.0, 101.0, 100.0, 99.0, 100.0],
            "close": [101.0, 102.0, 99.0, 98.0, 100.0],
            "signal": [
                "hold",
                "enter_long",
                "hold",
                "exit_long",
                "hold",
            ],
        }
    )
    result = run_backtest(bars)
    equity = result.equity_curve["equity"]
    expected_drawdown = (equity - equity.cummax()) / equity.cummax()

    pd.testing.assert_series_equal(
        result.equity_curve["drawdown"],
        expected_drawdown,
        check_names=False,
    )

    assert result.equity_curve["drawdown"].min() == pytest.approx(
        expected_drawdown.min()
    )


def test_cash_and_position_value_are_reflected_in_equity_each_row() -> None:
    result = run_backtest(sample_bars())
    equity_curve = result.equity_curve

    pd.testing.assert_series_equal(
        equity_curve["equity"],
        equity_curve["cash"] + equity_curve["position_quantity"] * equity_curve["close"],
        check_names=False,
    )


def test_losing_and_winning_trades_have_correct_post_exit_cash() -> None:
    bars = pd.DataFrame(
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
            "open": [100.0, 101.0, 100.0, 98.0, 99.0],
            "close": [100.0, 101.0, 100.0, 98.0, 99.0],
            "signal": [
                "hold",
                "enter_long",
                "hold",
                "exit_long",
                "hold",
            ],
        }
    )
    result = run_backtest(bars)
    last_row = result.equity_curve.iloc[-1]

    # Entry at row 2 open = 100, exit_long on row 3 exits at row 4 open = 99.
    assert last_row["cash"] == pytest.approx(9_999.0)
    assert last_row["equity"] == pytest.approx(9_999.0)


def test_winning_trade_realizes_proceeds_on_next_bar_open() -> None:
    bars = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2026-01-05T14:30:00Z",
                    "2026-01-05T14:45:00Z",
                    "2026-01-05T15:00:00Z",
                    "2026-01-05T15:15:00Z",
                    "2026-01-05T15:30:00Z",
                    "2026-01-05T15:45:00Z",
                ],
                utc=True,
            ),
            "open": [100.0, 101.0, 100.0, 102.0, 104.0, 104.0],
            "close": [100.0, 101.0, 100.0, 102.0, 104.0, 104.0],
            "signal": [
                "hold",
                "enter_long",
                "hold",
                "hold",
                "exit_long",
                "hold",
            ],
        }
    )
    result = run_backtest(bars)
    last_row = result.equity_curve.iloc[-1]

    # Entry at row 2 open = 100, exit_long on row 4 exits at row 5 open = 104.
    assert last_row["cash"] == pytest.approx(10_004.0)
    assert last_row["equity"] == pytest.approx(10_004.0)


def test_exit_adjusts_cash_to_realized_proceeds() -> None:
    bars = sample_bars().copy(deep=True)
    result = run_backtest(bars)

    equity_curve = result.equity_curve
    exit_row = equity_curve.iloc[4]
    assert exit_row["cash"] == pytest.approx(10_002.0)


def test_drawdown_uses_running_peak_equity() -> None:
    bars = sample_bars().copy(deep=True)
    result = run_backtest(bars)

    equity_curve = result.equity_curve
    assert equity_curve["running_peak_equity"].is_monotonic_increasing
    assert equity_curve["drawdown"].min() == pytest.approx(
        (equity_curve["equity"] - equity_curve["running_peak_equity"]).min() / equity_curve["running_peak_equity"].iloc[0]
    )


def test_maximum_drawdown_matches_known_series() -> None:
    bars = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2026-01-05T14:30:00Z",
                    "2026-01-05T14:45:00Z",
                    "2026-01-05T15:00:00Z",
                    "2026-01-05T15:15:00Z",
                ],
                utc=True,
            ),
            "open": [100.0, 101.0, 102.0, 99.0],
            "close": [101.0, 102.0, 99.0, 100.0],
            "signal": [
                "hold",
                "enter_long",
                "exit_long",
                "hold",
            ],
        }
    )
    result = run_backtest(bars)
    metrics = PerformanceMetrics.from_backtest_result(result)

    assert metrics.maximum_drawdown_pct == pytest.approx(0.03)


def test_total_return_is_correct() -> None:
    result = run_backtest(sample_bars())
    metrics = PerformanceMetrics.from_backtest_result(result)

    assert metrics.total_return_pct == pytest.approx(0.02)


def test_win_rate_is_correct() -> None:
    result = run_backtest(sample_bars())
    metrics = PerformanceMetrics.from_backtest_result(result)

    assert metrics.win_rate_pct == pytest.approx(100.0)


def test_average_winner_and_loser_match() -> None:
    bars = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2026-01-05T14:30:00Z",
                    "2026-01-05T14:45:00Z",
                    "2026-01-05T15:00:00Z",
                    "2026-01-05T15:15:00Z",
                    "2026-01-05T15:30:00Z",
                    "2026-01-05T15:45:00Z",
                ],
                utc=True,
            ),
            "open": [100.0, 101.0, 102.0, 100.0, 100.0, 100.0],
            "close": [101.0, 102.0, 100.0, 100.0, 101.0, 101.0],
            "signal": [
                "hold",
                "enter_long",
                "exit_long",
                "hold",
                "enter_long",
                "exit_long",
            ],
        }
    )
    result = run_backtest(bars)
    metrics = PerformanceMetrics.from_backtest_result(result)

    assert metrics.average_winner == pytest.approx(1.0)
    assert metrics.average_loser == pytest.approx(-2.0)
    assert metrics.largest_winner == pytest.approx(1.0)
    assert metrics.largest_loser == pytest.approx(-2.0)


def test_profit_factor_handles_no_losing_trades() -> None:
    result = run_backtest(sample_bars())
    metrics = PerformanceMetrics.from_backtest_result(result)

    assert metrics.profit_factor is None


def test_no_trades_do_not_crash() -> None:
    bars = sample_bars().copy(deep=True)
    bars["signal"] = ["hold"] * len(bars)
    result = run_backtest(bars)
    metrics = PerformanceMetrics.from_backtest_result(result)

    assert metrics.number_of_trades == 0
    assert metrics.win_rate_pct is None
    assert metrics.profit_factor is None


def test_no_winning_trades_do_not_crash() -> None:
    bars = sample_bars().copy(deep=True)
    bars["open"] = [100.0, 101.0, 100.0, 99.0, 98.0]
    bars["close"] = [101.0, 100.0, 99.0, 98.0, 97.0]
    bars["signal"] = ["hold", "enter_long", "hold", "exit_long", "hold"]
    result = run_backtest(bars)
    metrics = PerformanceMetrics.from_backtest_result(result)

    assert metrics.winning_trades == 0
    assert metrics.losing_trades == 1
    assert metrics.average_winner is None
    assert metrics.profit_factor is None


def test_no_losing_trades_do_not_crash() -> None:
    result = run_backtest(sample_bars())
    metrics = PerformanceMetrics.from_backtest_result(result)

    assert metrics.losing_trades == 0
    assert metrics.average_loser is None


def test_zero_exposure_is_handled_correctly() -> None:
    bars = sample_bars().copy(deep=True)
    bars["signal"] = ["hold"] * len(bars)
    result = run_backtest(bars)
    metrics = PerformanceMetrics.from_backtest_result(result)

    assert metrics.exposure_pct == pytest.approx(0.0)


def test_exposure_percentage_is_correct() -> None:
    bars = sample_bars().copy(deep=True)
    bars["signal"] = ["hold", "enter_long", "hold", "hold", "hold"]
    result = run_backtest(bars)
    metrics = PerformanceMetrics.from_backtest_result(result)

    assert metrics.exposure_pct == pytest.approx(3 / 5 * 100)


def test_buy_and_hold_baseline_is_correct() -> None:
    result = run_backtest(sample_bars())
    metrics = PerformanceMetrics.from_backtest_result(result)

    assert metrics.baseline_gross_pnl == pytest.approx(5.0)
    assert metrics.baseline_return_pct == pytest.approx(0.05)
    assert "buy-and-hold" in metrics.baseline_note


def test_trade_csv_contains_required_columns(tmp_path: Path) -> None:
    result = run_backtest(sample_bars())
    path = tmp_path / "trade_log.csv"
    export_trade_log_csv(result.to_frame(), path)
    loaded = pd.read_csv(path)

    expected_columns = {
        "symbol",
        "entry_signal_time",
        "entry_time",
        "entry_price",
        "exit_signal_time",
        "exit_time",
        "exit_price",
        "quantity",
        "exit_reason",
        "gross_pnl",
        "return_pct",
        "bars_held",
    }
    assert expected_columns.issubset(set(loaded.columns))


def test_equity_csv_contains_required_columns(tmp_path: Path) -> None:
    result = run_backtest(sample_bars())
    path = tmp_path / "equity_curve.csv"
    export_equity_curve_csv(result.equity_curve, path)
    loaded = pd.read_csv(path)

    expected_columns = {
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
    }
    assert expected_columns.issubset(set(loaded.columns))


def test_summary_json_contains_required_metrics(tmp_path: Path) -> None:
    result = run_backtest(sample_bars())
    metrics = PerformanceMetrics.from_backtest_result(result)
    path = tmp_path / "summary.json"
    export_performance_summary_json(metrics.to_dict(), path)

    loaded = json.loads(path.read_text(encoding="utf-8"))
    expected_keys = {
        "starting_cash",
        "ending_cash",
        "gross_pnl",
        "total_return_pct",
        "maximum_drawdown_pct",
        "number_of_trades",
        "winning_trades",
        "losing_trades",
        "win_rate_pct",
        "average_trade_pnl",
        "average_winner",
        "average_loser",
        "largest_winner",
        "largest_loser",
        "profit_factor",
        "exposure_pct",
        "baseline_gross_pnl",
        "baseline_return_pct",
        "baseline_note",
    }
    assert expected_keys.issubset(set(loaded.keys()))


def test_existing_output_files_are_not_overwritten_by_default(tmp_path: Path) -> None:
    result = run_backtest(sample_bars())
    path = tmp_path / "trade_log.csv"
    export_trade_log_csv(result.to_frame(), path)
    with pytest.raises(FileExistsError):
        export_trade_log_csv(result.to_frame(), path)


def test_overwrite_true_permits_replacement(tmp_path: Path) -> None:
    result = run_backtest(sample_bars())
    path = tmp_path / "trade_log.csv"
    export_trade_log_csv(result.to_frame(), path)
    exported_path = export_trade_log_csv(result.to_frame(), path, overwrite=True)
    assert exported_path.exists()


def test_input_dataframes_are_not_modified() -> None:
    original = sample_bars()
    original_copy = original.copy(deep=True)
    run_backtest(original)
    pd.testing.assert_frame_equal(original, original_copy)


def test_trade_objects_are_not_modified() -> None:
    result = run_backtest(sample_bars())
    trades = result.trades
    trade = trades[0]
    assert trade.gross_pnl == pytest.approx(2.0)
    assert trade.return_pct == pytest.approx(2.0 / 102.0)


def test_export_backtest_report(tmp_path: Path) -> None:
    result = run_backtest(sample_bars())
    metrics = PerformanceMetrics.from_backtest_result(result)
    paths = export_backtest_report(
        trades=result.to_frame(),
        equity_curve=result.equity_curve,
        summary=metrics.to_dict(),
        experiment_name="test_experiment",
        root=tmp_path,
    )

    assert paths["trade_log"].exists()
    assert paths["equity_curve"].exists()
    assert paths["performance_summary"].exists()
