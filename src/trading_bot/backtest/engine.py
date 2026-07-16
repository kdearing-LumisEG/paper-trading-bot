"""Bar-by-bar backtest engine for deterministic, long-only simulation."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from trading_bot.backtest.costs import (
    ExecutionCostModel,
)
from trading_bot.backtest.models import (
    BacktestResult,
    SkippedEntry,
    Trade,
)
from trading_bot.backtest.position_sizing import (
    PositionSizingModel,
)


VALID_SIGNALS = {
    "hold",
    "enter_long",
    "exit_long",
}


class BacktestError(ValueError):
    """Raised when backtest inputs fail validation."""


def _normalize_timestamp(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    result = frame.copy(deep=True)

    result["timestamp"] = pd.to_datetime(
        result["timestamp"],
        utc=True,
        errors="raise",
    )

    return result


def _validate_bar_input(
    frame: pd.DataFrame,
    starting_cash: float,
) -> pd.DataFrame:
    if frame.empty:
        raise BacktestError(
            "Input frame cannot be empty."
        )

    required_columns = {
        "timestamp",
        "open",
        "close",
        "signal",
    }

    missing_columns = required_columns.difference(
        frame.columns
    )

    if missing_columns:
        missing = ", ".join(
            sorted(missing_columns)
        )

        raise BacktestError(
            f"Missing required columns: {missing}"
        )

    if starting_cash <= 0:
        raise BacktestError(
            "starting_cash must be positive."
        )

    result = _normalize_timestamp(frame)

    if result["timestamp"].isna().any():
        raise BacktestError(
            "Timestamp values cannot be null."
        )

    if result["timestamp"].duplicated().any():
        raise BacktestError(
            "Duplicate timestamps cannot be processed."
        )

    if not result[
        "timestamp"
    ].is_monotonic_increasing:
        raise BacktestError(
            "Rows must be ordered by timestamp."
        )

    for column in ["open", "close"]:
        if not pd.api.types.is_numeric_dtype(
            result[column]
        ):
            result[column] = pd.to_numeric(
                result[column],
                errors="raise",
            )

        if (result[column] <= 0).any():
            raise BacktestError(
                f"{column.capitalize()} prices "
                "must be positive."
            )

    unknown_signals = set(
        result["signal"]
    ).difference(VALID_SIGNALS)

    if unknown_signals:
        unknown = ", ".join(
            sorted(unknown_signals)
        )

        raise BacktestError(
            f"Unknown signal values: {unknown}"
        )

    return result


def _session_date(
    timestamp: pd.Timestamp,
) -> pd.Timestamp:
    return (
        timestamp
        .tz_convert("America/New_York")
        .normalize()
    )


def _build_trade(
    symbol: str | None,
    entry_signal_time: datetime,
    entry_time: datetime,
    entry_reference_price: float,
    entry_price: float,
    entry_commission: float,
    exit_signal_time: datetime | None,
    exit_time: datetime,
    exit_reference_price: float,
    exit_price: float,
    exit_commission: float,
    quantity: int,
    exit_reason: str,
    bars_held: int,
) -> Trade:
    gross_pnl = (
        exit_reference_price
        - entry_reference_price
    ) * quantity

    entry_slippage_cost = (
        entry_price
        - entry_reference_price
    ) * quantity

    exit_slippage_cost = (
        exit_reference_price
        - exit_price
    ) * quantity

    slippage_cost = (
        entry_slippage_cost
        + exit_slippage_cost
    )

    total_costs = (
        entry_commission
        + exit_commission
        + slippage_cost
    )

    net_pnl = gross_pnl - total_costs

    capital_basis = (
        entry_reference_price
        * quantity
    )

    return_pct = (
        net_pnl / capital_basis
        if capital_basis != 0
        else 0.0
    )

    return Trade(
        symbol=symbol,
        entry_signal_time=entry_signal_time,
        entry_time=entry_time,
        entry_reference_price=(
            entry_reference_price
        ),
        entry_price=entry_price,
        entry_commission=entry_commission,
        exit_signal_time=exit_signal_time,
        exit_time=exit_time,
        exit_reference_price=(
            exit_reference_price
        ),
        exit_price=exit_price,
        exit_commission=exit_commission,
        quantity=quantity,
        exit_reason=exit_reason,
        gross_pnl=gross_pnl,
        slippage_cost=slippage_cost,
        total_costs=total_costs,
        net_pnl=net_pnl,
        return_pct=return_pct,
        bars_held=bars_held,
    )


def _execute_exit(
    *,
    cost_model: ExecutionCostModel,
    symbol: str | None,
    entry_signal_time: datetime,
    entry_time: datetime,
    entry_reference_price: float,
    entry_price: float,
    entry_commission: float,
    exit_signal_time: datetime | None,
    exit_time: datetime,
    exit_reference_price: float,
    quantity: int,
    exit_reason: str,
    bars_held: int,
) -> tuple[Trade, float]:
    exit_price = cost_model.adjusted_fill_price(
        reference_price=exit_reference_price,
        side="sell",
    )

    exit_commission = (
        cost_model.commission_for_order(
            quantity
        )
    )

    trade = _build_trade(
        symbol=symbol,
        entry_signal_time=entry_signal_time,
        entry_time=entry_time,
        entry_reference_price=(
            entry_reference_price
        ),
        entry_price=entry_price,
        entry_commission=entry_commission,
        exit_signal_time=exit_signal_time,
        exit_time=exit_time,
        exit_reference_price=(
            exit_reference_price
        ),
        exit_price=exit_price,
        exit_commission=exit_commission,
        quantity=quantity,
        exit_reason=exit_reason,
        bars_held=bars_held,
    )

    cash_proceeds = (
        exit_price * quantity
        - exit_commission
    )

    return trade, cash_proceeds


def run_backtest(
    frame: pd.DataFrame,
    starting_cash: float = 10_000.0,
    symbol: str | None = None,
    cost_model: ExecutionCostModel | None = None,
    position_sizing: PositionSizingModel | None = None,
) -> BacktestResult:
    """Run a deterministic next-bar-open backtest."""

    bars = _validate_bar_input(
        frame,
        starting_cash,
    ).reset_index(drop=True)

    execution_costs = (
        cost_model
        if cost_model is not None
        else ExecutionCostModel()
    )
    sizing_model = (
        position_sizing
        if position_sizing is not None
        else PositionSizingModel()
    )

    if symbol is None and "symbol" in bars.columns:
        unique_symbols = (
            bars["symbol"]
            .dropna()
            .unique()
        )

        symbol = (
            str(unique_symbols[0])
            if len(unique_symbols)
            else None
        )

    trades: list[Trade] = []
    skipped_entries: list[SkippedEntry] = []
    equity_rows: list[dict[str, object]] = []

    position_open = False
    position_quantity = 0

    entry_reference_price = 0.0
    entry_price = 0.0
    entry_commission = 0.0

    entry_time: pd.Timestamp | None = None
    entry_signal_time: pd.Timestamp | None = None
    entry_index: int | None = None

    current_cash = starting_cash

    for index in range(len(bars)):
        row = bars.iloc[index]
        current_time = row["timestamp"]

        current_session = _session_date(
            current_time
        )

        next_session = (
            _session_date(
                bars.iloc[index + 1][
                    "timestamp"
                ]
            )
            if index + 1 < len(bars)
            else current_session
        )

        last_bar_of_session = (
            index == len(bars) - 1
            or next_session != current_session
        )

        if index > 0:
            previous_row = bars.iloc[index - 1]

            previous_session = _session_date(
                previous_row["timestamp"]
            )

            if (
                position_open
                and previous_session
                != current_session
            ):
                assert entry_signal_time is not None
                assert entry_time is not None
                assert entry_index is not None

                trade, cash_proceeds = (
                    _execute_exit(
                        cost_model=execution_costs,
                        symbol=symbol,
                        entry_signal_time=(
                            entry_signal_time
                        ),
                        entry_time=entry_time,
                        entry_reference_price=(
                            entry_reference_price
                        ),
                        entry_price=entry_price,
                        entry_commission=(
                            entry_commission
                        ),
                        exit_signal_time=None,
                        exit_time=previous_row[
                            "timestamp"
                        ],
                        exit_reference_price=float(
                            previous_row["close"]
                        ),
                        quantity=(
                            position_quantity
                        ),
                        exit_reason=(
                            "session_close"
                        ),
                        bars_held=(
                            index - entry_index
                        ),
                    )
                )

                trades.append(trade)
                current_cash += cash_proceeds

                position_open = False
                position_quantity = 0

            if (
                previous_row["signal"]
                == "enter_long"
                and not position_open
                and previous_session
                == current_session
            ):
                candidate_reference_price = float(
                    row["open"]
                )

                candidate_fill_price = (
                    execution_costs
                    .adjusted_fill_price(
                        reference_price=(
                            candidate_reference_price
                        ),
                        side="buy",
                    )
                )

                requested_quantity = (
                    sizing_model.quantity
                )

                candidate_commission = (
                    execution_costs
                    .commission_for_order(
                        requested_quantity
                    )
                )

                entry_quantity = (
                    sizing_model
                    .quantity_for_entry(
                        fill_price=(
                            candidate_fill_price
                        ),
                        available_cash=(
                            current_cash
                        ),
                        commission=(
                            candidate_commission
                        ),
                    )
                )

                if entry_quantity == 0:
                    required_cash = (
                        sizing_model.required_cash(
                            fill_price=(
                                candidate_fill_price
                            ),
                            commission=(
                                candidate_commission
                            ),
                        )
                    )

                    skipped_entries.append(
                        SkippedEntry(
                            symbol=symbol,
                            signal_time=(
                                previous_row[
                                    "timestamp"
                                ]
                            ),
                            execution_time=(
                                current_time
                            ),
                            reference_price=(
                                candidate_reference_price
                            ),
                            adjusted_fill_price=(
                                candidate_fill_price
                            ),
                            requested_quantity=(
                                requested_quantity
                            ),
                            required_cash=(
                                required_cash
                            ),
                            available_cash=(
                                current_cash
                            ),
                            max_cash_fraction=(
                                sizing_model
                                .max_cash_fraction
                            ),
                            reason=(
                                "insufficient_cash_or_"
                                "allocation_limit"
                            ),
                        )
                    )

                else:
                    position_open = True
                    position_quantity = (
                        entry_quantity
                    )

                    entry_reference_price = (
                        candidate_reference_price
                    )

                    entry_price = (
                        candidate_fill_price
                    )

                    entry_commission = (
                        candidate_commission
                    )

                    entry_time = current_time
                    entry_signal_time = (
                        previous_row["timestamp"]
                    )
                    entry_index = index

                    current_cash -= (
                        entry_price
                        * position_quantity
                        + entry_commission
                    )

            if (
                previous_row["signal"]
                == "exit_long"
                and position_open
                and previous_session
                == current_session
            ):
                assert entry_signal_time is not None
                assert entry_time is not None
                assert entry_index is not None

                trade, cash_proceeds = (
                    _execute_exit(
                        cost_model=execution_costs,
                        symbol=symbol,
                        entry_signal_time=(
                            entry_signal_time
                        ),
                        entry_time=entry_time,
                        entry_reference_price=(
                            entry_reference_price
                        ),
                        entry_price=entry_price,
                        entry_commission=(
                            entry_commission
                        ),
                        exit_signal_time=(
                            previous_row[
                                "timestamp"
                            ]
                        ),
                        exit_time=current_time,
                        exit_reference_price=float(
                            row["open"]
                        ),
                        quantity=(
                            position_quantity
                        ),
                        exit_reason="signal",
                        bars_held=(
                            index - entry_index
                        ),
                    )
                )

                trades.append(trade)
                current_cash += cash_proceeds

                position_open = False
                position_quantity = 0

        position_market_value = (
            position_quantity
            * float(row["close"])
        )

        equity = (
            current_cash
            + position_market_value
        )

        equity_rows.append(
            {
                "timestamp": current_time,
                "open": row["open"],
                "close": row["close"],
                "cash": current_cash,
                "position_quantity": (
                    position_quantity
                ),
                "position_market_value": (
                    position_market_value
                ),
                "equity": equity,
                "is_exposed": (
                    position_quantity != 0
                ),
            }
        )

        if (
            position_open
            and last_bar_of_session
        ):
            assert entry_signal_time is not None
            assert entry_time is not None
            assert entry_index is not None

            trade, cash_proceeds = (
                _execute_exit(
                    cost_model=execution_costs,
                    symbol=symbol,
                    entry_signal_time=(
                        entry_signal_time
                    ),
                    entry_time=entry_time,
                    entry_reference_price=(
                        entry_reference_price
                    ),
                    entry_price=entry_price,
                    entry_commission=(
                        entry_commission
                    ),
                    exit_signal_time=None,
                    exit_time=current_time,
                    exit_reference_price=float(
                        row["close"]
                    ),
                    quantity=position_quantity,
                    exit_reason="session_close",
                    bars_held=(
                        index - entry_index + 1
                    ),
                )
            )

            trades.append(trade)
            current_cash += cash_proceeds

            position_open = False
            position_quantity = 0

           

    equity_curve = pd.DataFrame(
        equity_rows
    )

    equity_curve[
        "running_peak_equity"
    ] = equity_curve["equity"].cummax()

    equity_curve["drawdown"] = (
        equity_curve["equity"]
        - equity_curve[
            "running_peak_equity"
        ]
    ) / equity_curve[
        "running_peak_equity"
    ]

    return BacktestResult.from_trades(
        trades=trades,
        starting_cash=starting_cash,
        equity_curve=equity_curve,
        skipped_entries=skipped_entries,
    )