"""Deterministic technical-indicator calculations."""

import pandas as pd


class IndicatorCalculationError(ValueError):
    """Raised when indicator inputs or parameters are invalid."""


def add_ema_indicators(
    frame: pd.DataFrame,
    fast_period: int,
    slow_period: int,
) -> pd.DataFrame:
    """Return a copy of the bars with fast and slow EMA columns.

    Indicators are calculated using only the current and previous rows.
    The original dataframe is not modified.
    """

    if frame.empty:
        raise IndicatorCalculationError(
            "Bar data cannot be empty."
        )

    if fast_period <= 0 or slow_period <= 0:
        raise IndicatorCalculationError(
            "EMA periods must be positive."
        )

    if fast_period >= slow_period:
        raise IndicatorCalculationError(
            "fast_period must be smaller than slow_period."
        )

    required_columns = {"timestamp", "close"}
    missing_columns = required_columns.difference(frame.columns)

    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise IndicatorCalculationError(
            f"Missing required columns: {missing}"
        )

    result = frame.copy(deep=True)

    try:
        result["timestamp"] = pd.to_datetime(
            result["timestamp"],
            utc=True,
            errors="raise",
        )

        result["close"] = pd.to_numeric(
            result["close"],
            errors="raise",
        )
    except (TypeError, ValueError) as exc:
        raise IndicatorCalculationError(
            "Timestamp or close-price conversion failed."
        ) from exc

    if result["timestamp"].isna().any():
        raise IndicatorCalculationError(
            "Timestamp values cannot be null."
        )

    if result["close"].isna().any():
        raise IndicatorCalculationError(
            "Close prices cannot be null."
        )

    if (result["close"] <= 0).any():
        raise IndicatorCalculationError(
            "Close prices must be positive."
        )

    if result["timestamp"].duplicated().any():
        raise IndicatorCalculationError(
            "Duplicate timestamps cannot be processed."
        )

    if not result["timestamp"].is_monotonic_increasing:
        raise IndicatorCalculationError(
            "Bars must be ordered by timestamp."
        )

    result["ema_fast"] = result["close"].ewm(
        span=fast_period,
        adjust=False,
        min_periods=fast_period,
    ).mean()

    result["ema_slow"] = result["close"].ewm(
        span=slow_period,
        adjust=False,
        min_periods=slow_period,
    ).mean()

    return result
