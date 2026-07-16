"""Bar-by-bar backtest engine for deterministic, long-only simulation."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from trading_bot.backtest.models import BacktestResult, Trade


VALID_SIGNALS = {"hold", "enter_long", "exit_long"}


class BacktestError(ValueError):
    """Raised when backtest inputs fail validation."""


def _normalize_timestamp(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy(deep=True)
    result["timestamp"] = pd.to_datetime(
        result["timestamp"],
        utc=True,
        errors="raise",
    )
    return result


def _validate_bar_input(frame: pd.DataFrame, starting_cash: float) -> pd.DataFrame:
    if frame.empty:
        raise BacktestError("Input frame cannot be empty.")

    required_columns = {"timestamp", "open", "close", "signal"}
    missing_columns = required_columns.difference(frame.columns)

    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise BacktestError(f"Missing required columns: {missing}")

    if starting_cash <= 0:
        raise BacktestError("starting_cash must be positive.")

    result = _normalize_timestamp(frame)

    if result["timestamp"].isna().any():
        raise BacktestError("Timestamp values cannot be null.")

    if result["timestamp"].duplicated().any():
        raise BacktestError("Duplicate timestamps cannot be processed.")

    if not result["timestamp"].is_monotonic_increasing:
        raise BacktestError("Rows must be ordered by timestamp.")

    for column in ["open", "close"]:
        if not pd.api.types.is_numeric_dtype(result[column]):
            result[column] = pd.to_numeric(result[column], errors="raise")
        if (result[column] <= 0).any():
            raise BacktestError(
                f"{column.capitalize()} prices must be positive."
            )

    unknown_signals = set(result["signal"]).difference(VALID_SIGNALS)

    if unknown_signals:
        unknown = ", ".join(sorted(unknown_signals))
        raise BacktestError(
            f"Unknown signal values: {unknown}"
        )

    return result


def _session_date(timestamp: pd.Timestamp) -> pd.Timestamp:
    return timestamp.tz_convert("America/New_York").normalize()


def _build_trade(
    symbol: str | None,
    entry_signal_time: datetime,
    entry_time: datetime,
    entry_price: float,
    exit_signal_time: datetime | None,
    exit_time: datetime,
    exit_price: float,
    quantity: int,
    exit_reason: str,
    bars_held: int,
) -> Trade:
    gross_pnl = (exit_price - entry_price) * quantity
    return_pct = gross_pnl / entry_price if entry_price != 0 else 0.0

    return Trade(
        symbol=symbol,
        entry_signal_time=entry_signal_time,
        entry_time=entry_time,
        entry_price=entry_price,
        exit_signal_time=exit_signal_time,
        exit_time=exit_time,
        exit_price=exit_price,
        quantity=quantity,
        exit_reason=exit_reason,
        gross_pnl=gross_pnl,
        return_pct=return_pct,
        bars_held=bars_held,
    )


def run_backtest(
    frame: pd.DataFrame,
    starting_cash: float = 10_000.0,
    symbol: str | None = None,
) -> BacktestResult:
    bars = _validate_bar_input(frame, starting_cash)
    bars = bars.reset_index(drop=True)

    if symbol is None and "symbol" in bars.columns:
        unique_symbols = bars["symbol"].dropna().unique()
        symbol = str(unique_symbols[0]) if len(unique_symbols) else None

    trades: list[Trade] = []
    equity_rows: list[dict[str, object]] = []
    position_open = False
    position_quantity = 0
    entry_price = 0.0
    entry_time: pd.Timestamp | None = None
    entry_signal_time: pd.Timestamp | None = None
    entry_index: int | None = None
    current_cash = starting_cash

    for index in range(len(bars)):
        row = bars.iloc[index]
        current_time = row["timestamp"]
        current_session = _session_date(row["timestamp"])
        next_session = (
            _session_date(bars.iloc[index + 1]["timestamp"])
            if index + 1 < len(bars)
            else current_session
        )
        last_bar_of_session = (
            index == len(bars) - 1
            or next_session != current_session
        )

        if index > 0:
            previous_row = bars.iloc[index - 1]
            previous_session = _session_date(previous_row["timestamp"])

            if position_open and previous_session != current_session:
                exit_price = previous_row["close"]
                exit_time = previous_row["timestamp"]
                trades.append(
                    _build_trade(
                        symbol,
                        entry_signal_time=entry_signal_time,
                        entry_time=entry_time,
                        entry_price=entry_price,
                        exit_signal_time=None,
                        exit_time=exit_time,
                        exit_price=exit_price,
                        quantity=position_quantity,
                        exit_reason="session_close",
                        bars_held=index - entry_index,
                    )
                )
                current_cash += exit_price * position_quantity
                position_open = False
                position_quantity = 0
                entry_price = 0.0
                entry_time = None
                entry_signal_time = None
                entry_index = None

            if previous_row["signal"] == "enter_long":
                if not position_open and previous_session == current_session:
                    position_open = True
                    position_quantity = 1
                    entry_price = row["open"]
                    entry_time = current_time
                    entry_signal_time = previous_row["timestamp"]
                    entry_index = index
                    current_cash -= entry_price * position_quantity

            if previous_row["signal"] == "exit_long":
                if position_open and previous_session == current_session:
                    exit_price = row["open"]
                    exit_time = current_time
                    trades.append(
                        _build_trade(
                            symbol,
                            entry_signal_time=entry_signal_time,
                            entry_time=entry_time,
                            entry_price=entry_price,
                            exit_signal_time=previous_row["timestamp"],
                            exit_time=exit_time,
                            exit_price=exit_price,
                            quantity=position_quantity,
                            exit_reason="signal",
                            bars_held=index - entry_index,
                        )
                    )
                    current_cash += exit_price * position_quantity
                    position_open = False
                    position_quantity = 0
                    entry_price = 0.0
                    entry_time = None
                    entry_signal_time = None
                    entry_index = None

        position_market_value = position_quantity * row["close"]
        equity = current_cash + position_market_value
        equity_rows.append(
            {
                "timestamp": current_time,
                "open": row["open"],
                "close": row["close"],
                "cash": current_cash,
                "position_quantity": position_quantity,
                "position_market_value": position_market_value,
                "equity": equity,
                "is_exposed": position_quantity != 0,
            }
        )

        if position_open and last_bar_of_session:
            exit_price = row["close"]
            exit_time = row["timestamp"]
            trades.append(
                _build_trade(
                    symbol,
                    entry_signal_time=entry_signal_time,
                    entry_time=entry_time,
                    entry_price=entry_price,
                    exit_signal_time=None,
                    exit_time=exit_time,
                    exit_price=exit_price,
                    quantity=position_quantity,
                    exit_reason="session_close",
                    bars_held=index - entry_index + 1,
                )
            )
            current_cash += exit_price * position_quantity
            position_open = False
            position_quantity = 0
            entry_price = 0.0
            entry_time = None
            entry_signal_time = None
            entry_index = None

    equity_curve = pd.DataFrame(equity_rows)
    equity_curve["running_peak_equity"] = equity_curve["equity"].cummax()
    equity_curve["drawdown"] = (
        equity_curve["equity"] - equity_curve["running_peak_equity"]
    ) / equity_curve["running_peak_equity"]

    return BacktestResult.from_trades(
        trades=trades,
        starting_cash=starting_cash,
        equity_curve=equity_curve,
    )
