"""Tests for the deterministic backtest engine."""

import pandas as pd
import pytest

from trading_bot.backtest.engine import BacktestError, run_backtest


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


def test_entry_executes_at_next_bar_open() -> None:
    result = run_backtest(sample_bars())

    assert result.number_of_trades == 1
    trade = result.trades[0]
    assert trade.entry_time == pd.Timestamp("2026-01-05T15:00:00Z")
    assert trade.entry_price == 102.0
    assert trade.exit_time == pd.Timestamp("2026-01-05T15:30:00Z")


def test_exit_executes_at_next_bar_open() -> None:
    bars = sample_bars().copy(deep=True)
    bars.at[2, "signal"] = "exit_long"
    bars.at[1, "signal"] = "hold"

    result = run_backtest(bars)

    assert result.number_of_trades == 0


def test_exit_signal_while_flat_produces_no_trade() -> None:
    bars = sample_bars().copy(deep=True)
    bars["signal"] = [
        "hold",
        "hold",
        "exit_long",
        "hold",
        "hold",
    ]

    result = run_backtest(bars)

    assert result.number_of_trades == 0


def test_repeated_entry_signals_while_long_do_not_duplicate_positions() -> None:
    bars = sample_bars().copy(deep=True)
    bars["signal"] = [
        "hold",
        "enter_long",
        "enter_long",
        "hold",
        "exit_long",
    ]

    result = run_backtest(bars)

    assert result.number_of_trades == 1


def test_open_position_is_force_closed_at_session_end() -> None:
    bars = sample_bars().copy(deep=True)
    bars["signal"] = [
        "hold",
        "enter_long",
        "hold",
        "hold",
        "hold",
    ]

    result = run_backtest(bars)

    assert result.number_of_trades == 1
    assert result.trades[0].exit_reason == "session_close"
    assert result.trades[0].exit_price == 105.0


def test_no_position_remains_overnight() -> None:
    bars = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2026-01-05T20:00:00Z",
                    "2026-01-05T20:15:00Z",
                    "2026-01-05T20:30:00Z",
                    "2026-01-05T20:45:00Z",
                ],
                utc=True,
            ),
            "open": [100.0, 101.0, 102.0, 103.0],
            "close": [101.0, 102.0, 103.0, 104.0],
            "signal": [
                "hold",
                "enter_long",
                "hold",
                "hold",
            ],
        }
    )

    result = run_backtest(bars)

    assert result.number_of_trades == 1
    trade = result.trades[0]
    assert trade.exit_reason == "session_close"
    assert trade.exit_price == 104.0
    assert trade.entry_time == pd.Timestamp("2026-01-05T20:30:00Z")


def test_signal_on_final_bar_does_not_execute_next_day_open() -> None:
    bars = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2026-01-05T20:30:00Z",
                    "2026-01-05T20:45:00Z",
                    "2026-01-06T13:30:00Z",
                ],
                utc=True,
            ),
            "open": [100.0, 101.0, 102.0],
            "close": [101.0, 102.0, 103.0],
            "signal": [
                "hold",
                "enter_long",
                "hold",
            ],
        }
    )

    result = run_backtest(bars)

    assert result.number_of_trades == 0


def test_gross_pnl_and_return_are_calculated() -> None:
    result = run_backtest(sample_bars())
    trade = result.trades[0]

    assert trade.gross_pnl == pytest.approx(2.0)
    assert trade.return_pct == pytest.approx(2.0 / 102.0)


def test_losing_trade_has_negative_pnl() -> None:
    bars = sample_bars().copy(deep=True)
    bars["open"] = [100.0, 99.0, 98.0, 97.0, 96.0]
    bars["close"] = [99.0, 98.0, 97.0, 96.0, 95.0]

    result = run_backtest(bars)

    assert result.trades[0].gross_pnl == pytest.approx(-2.0)


def test_input_dataframe_is_not_modified() -> None:
    original = sample_bars()
    original_copy = original.copy(deep=True)

    run_backtest(original)

    pd.testing.assert_frame_equal(original, original_copy)


def test_missing_columns_fail() -> None:
    frame = sample_bars().drop(columns=["open"])

    with pytest.raises(BacktestError, match="Missing required columns"):
        run_backtest(frame)


def test_duplicate_timestamps_fail() -> None:
    frame = pd.concat(
        [sample_bars(), sample_bars().iloc[[0]]],
        ignore_index=True,
    )

    with pytest.raises(BacktestError, match="Duplicate timestamps"):
        run_backtest(frame)


def test_unordered_timestamps_fail() -> None:
    frame = sample_bars().iloc[::-1].reset_index(drop=True)

    with pytest.raises(BacktestError, match="ordered by timestamp"):
        run_backtest(frame)


def test_empty_input_fails() -> None:
    with pytest.raises(BacktestError, match="cannot be empty"):
        run_backtest(pd.DataFrame())


def test_unknown_signal_values_fail() -> None:
    frame = sample_bars().copy(deep=True)
    frame.at[1, "signal"] = "buy"

    with pytest.raises(BacktestError, match="Unknown signal values"):
        run_backtest(frame)
