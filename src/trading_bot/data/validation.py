"""Validation and normalization for historical market bars."""

import pandas as pd


REQUIRED_BAR_COLUMNS = (
    "symbol",
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
)

NUMERIC_BAR_COLUMNS = (
    "open",
    "high",
    "low",
    "close",
    "volume",
)


class BarValidationError(ValueError):
    """Raised when historical bar data fails validation."""


def validate_bars(
    frame: pd.DataFrame,
    expected_symbol: str,
    timeframe_minutes: int,
) -> pd.DataFrame:
    """Return normalized bars or raise an error for invalid data."""

    if timeframe_minutes <= 0:
        raise BarValidationError("timeframe_minutes must be positive.")

    if frame.empty:
        raise BarValidationError("Bar data cannot be empty.")

    missing_columns = set(REQUIRED_BAR_COLUMNS).difference(frame.columns)

    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise BarValidationError(f"Missing required columns: {missing}")

    bars = frame.loc[:, REQUIRED_BAR_COLUMNS].copy()

    if bars.isna().any().any():
        null_columns = bars.columns[bars.isna().any()].tolist()
        raise BarValidationError(
            f"Null values found in columns: {', '.join(null_columns)}"
        )

    bars["symbol"] = (
        bars["symbol"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    try:
        bars["timestamp"] = pd.to_datetime(
            bars["timestamp"],
            utc=True,
            errors="raise",
        )

        for column in NUMERIC_BAR_COLUMNS:
            bars[column] = pd.to_numeric(
                bars[column],
                errors="raise",
            )
    except (TypeError, ValueError) as exc:
        raise BarValidationError(
            "Timestamp or numeric conversion failed."
        ) from exc

    expected = expected_symbol.strip().upper()

    unexpected_symbols = set(bars["symbol"]) - {expected}

    if unexpected_symbols:
        received = ", ".join(sorted(unexpected_symbols))
        raise BarValidationError(
            f"Expected only {expected}, but received: {received}"
        )

    duplicate_rows = bars.duplicated(
        subset=["symbol", "timestamp"],
        keep=False,
    )

    if duplicate_rows.any():
        raise BarValidationError(
            "Duplicate symbol and timestamp combinations found."
        )

    aligned_timestamps = bars["timestamp"].dt.floor(
        f"{timeframe_minutes}min"
    )

    if not bars["timestamp"].eq(aligned_timestamps).all():
        raise BarValidationError(
            f"One or more timestamps are not aligned to "
            f"{timeframe_minutes}-minute intervals."
        )

    price_columns = ["open", "high", "low", "close"]

    if (bars[price_columns] <= 0).any().any():
        raise BarValidationError("OHLC prices must be positive.")

    if (bars["volume"] < 0).any():
        raise BarValidationError("Volume cannot be negative.")

    highest_component = bars[
        ["open", "low", "close"]
    ].max(axis=1)

    if (bars["high"] < highest_component).any():
        raise BarValidationError(
            "A high price is below another OHLC value."
        )

    lowest_component = bars[
        ["open", "high", "close"]
    ].min(axis=1)

    if (bars["low"] > lowest_component).any():
        raise BarValidationError(
            "A low price is above another OHLC value."
        )

    bars = bars.sort_values(
        ["symbol", "timestamp"]
    ).reset_index(drop=True)

    if not bars["timestamp"].is_monotonic_increasing:
        raise BarValidationError(
            "Timestamps are not strictly ordered."
        )

    return bars


def filter_regular_session_bars(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    """Keep weekday bars from 9:30 a.m. through 4:00 p.m. Eastern."""

    timestamps = pd.to_datetime(
        frame["timestamp"],
        utc=True,
        errors="raise",
    )

    eastern = timestamps.dt.tz_convert(
        "America/New_York"
    )

    minute_of_day = (
        eastern.dt.hour * 60
        + eastern.dt.minute
    )

    regular_session = (
        (eastern.dt.weekday < 5)
        & (minute_of_day >= 9 * 60 + 30)
        & (minute_of_day < 16 * 60)
    )

    return frame.loc[regular_session].reset_index(drop=True)
