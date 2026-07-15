"""Generate deterministic EMA crossover signals."""

import pandas as pd


class SignalGenerationError(ValueError):
    """Raised when signal inputs are invalid."""


def add_crossover_signals(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    """Return a copy of the data with EMA crossover signals.

    Signals are generated only when both the current and previous
    bars contain valid EMA values.
    """

    if frame.empty:
        raise SignalGenerationError(
            "Indicator data cannot be empty."
        )

    required_columns = {
        "timestamp",
        "ema_fast",
        "ema_slow",
    }

    missing_columns = required_columns.difference(frame.columns)

    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise SignalGenerationError(
            f"Missing required columns: {missing}"
        )

    result = frame.copy(deep=True)

    try:
        result["timestamp"] = pd.to_datetime(
            result["timestamp"],
            utc=True,
            errors="raise",
        )

        result["ema_fast"] = pd.to_numeric(
            result["ema_fast"],
            errors="coerce",
        )

        result["ema_slow"] = pd.to_numeric(
            result["ema_slow"],
            errors="coerce",
        )
    except (TypeError, ValueError) as exc:
        raise SignalGenerationError(
            "Timestamp or EMA conversion failed."
        ) from exc

    if result["timestamp"].isna().any():
        raise SignalGenerationError(
            "Timestamp values cannot be null."
        )

    if result["timestamp"].duplicated().any():
        raise SignalGenerationError(
            "Duplicate timestamps cannot be processed."
        )

    if not result["timestamp"].is_monotonic_increasing:
        raise SignalGenerationError(
            "Rows must be ordered by timestamp."
        )

    previous_fast = result["ema_fast"].shift(1)
    previous_slow = result["ema_slow"].shift(1)

    indicators_ready = (
        result["ema_fast"].notna()
        & result["ema_slow"].notna()
        & previous_fast.notna()
        & previous_slow.notna()
    )

    entry_signal = (
        indicators_ready
        & (previous_fast <= previous_slow)
        & (result["ema_fast"] > result["ema_slow"])
    )

    exit_signal = (
        indicators_ready
        & (previous_fast >= previous_slow)
        & (result["ema_fast"] < result["ema_slow"])
    )

    result["entry_signal"] = entry_signal
    result["exit_signal"] = exit_signal
    result["signal"] = "hold"

    result.loc[
        result["entry_signal"],
        "signal",
    ] = "enter_long"

    result.loc[
        result["exit_signal"],
        "signal",
    ] = "exit_long"

    return result
