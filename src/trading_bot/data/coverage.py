"""Audit historical bars against expected exchange sessions."""

from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd
import pandas_market_calendars as mcal


@dataclass(frozen=True)
class SessionCoverageAudit:
    """Results from comparing bars with an exchange calendar."""

    sessions: pd.DataFrame
    missing_timestamps: pd.DatetimeIndex
    unexpected_timestamps: pd.DatetimeIndex

    @property
    def is_complete(self) -> bool:
        """Return whether every expected bar is present."""

        return (
            not self.sessions.empty
            and bool(self.sessions["complete"].all())
            and self.missing_timestamps.empty
            and self.unexpected_timestamps.empty
        )


def audit_session_coverage(
    frame: pd.DataFrame,
    timeframe_minutes: int,
    start: datetime,
    end: datetime,
    calendar_name: str = "NYSE",
) -> SessionCoverageAudit:
    """Compare bar timestamps with expected exchange-session bars.

    The start time is inclusive and the end time is exclusive.
    """

    if timeframe_minutes <= 0:
        raise ValueError("timeframe_minutes must be positive.")

    if end <= start:
        raise ValueError("end must occur after start.")

    if frame.empty:
        raise ValueError("Bar data cannot be empty.")

    if "timestamp" not in frame.columns:
        raise ValueError("Bar data must include a timestamp column.")

    timestamps = pd.DatetimeIndex(
        pd.to_datetime(
            frame["timestamp"],
            utc=True,
            errors="raise",
        )
    ).sort_values()

    if timestamps.has_duplicates:
        raise ValueError("Duplicate timestamps cannot be audited.")

    calendar = mcal.get_calendar(calendar_name)

    final_included_time = end - timedelta(microseconds=1)

    schedule = calendar.schedule(
        start_date=start.date(),
        end_date=final_included_time.date(),
    )

    if schedule.empty:
        raise ValueError(
            "The requested window contains no trading sessions."
        )

    all_expected = pd.DatetimeIndex([], tz="UTC")
    session_rows: list[dict[str, object]] = []

    for session_date, session in schedule.iterrows():
        market_open = pd.Timestamp(
            session["market_open"]
        ).tz_convert("UTC")

        market_close = pd.Timestamp(
            session["market_close"]
        ).tz_convert("UTC")

        expected = pd.date_range(
            start=market_open,
            end=market_close,
            freq=f"{timeframe_minutes}min",
            inclusive="left",
        )

        actual = timestamps[
            (timestamps >= market_open)
            & (timestamps < market_close)
        ]

        missing = expected.difference(actual)
        unexpected = actual.difference(expected)

        all_expected = all_expected.union(expected)

        session_rows.append(
            {
                "session_date": session_date.date(),
                "market_open": market_open,
                "market_close": market_close,
                "expected_bars": len(expected),
                "actual_bars": len(actual),
                "missing_bars": len(missing),
                "unexpected_bars": len(unexpected),
                "complete": (
                    len(missing) == 0
                    and len(unexpected) == 0
                ),
            }
        )

    session_report = pd.DataFrame(session_rows)

    return SessionCoverageAudit(
        sessions=session_report,
        missing_timestamps=all_expected.difference(timestamps),
        unexpected_timestamps=timestamps.difference(all_expected),
    )

def filter_exchange_session_bars(
    frame: pd.DataFrame,
    calendar_name: str = "NYSE",
) -> pd.DataFrame:
    """Keep only bars inside each scheduled exchange session.

    Unlike a fixed 9:30 a.m. through 4:00 p.m. filter, this respects
    holidays and scheduled early closes.
    """

    if frame.empty:
        return frame.copy(deep=True)

    if "timestamp" not in frame.columns:
        raise ValueError(
            "Bar data must include a timestamp column."
        )

    result = frame.copy(deep=True)

    timestamps = pd.to_datetime(
        result["timestamp"],
        utc=True,
        errors="raise",
    )

    eastern_dates = (
        timestamps
        .dt.tz_convert("America/New_York")
        .dt.date
    )

    calendar = mcal.get_calendar(
        calendar_name
    )

    schedule = calendar.schedule(
        start_date=min(eastern_dates),
        end_date=max(eastern_dates),
    )

    session_windows: dict[
        object,
        tuple[pd.Timestamp, pd.Timestamp],
    ] = {}

    for session_date, session in schedule.iterrows():
        session_windows[
            session_date.date()
        ] = (
            pd.Timestamp(
                session["market_open"]
            ).tz_convert("UTC"),
            pd.Timestamp(
                session["market_close"]
            ).tz_convert("UTC"),
        )

    keep_rows: list[bool] = []

    for timestamp, session_date in zip(
        timestamps,
        eastern_dates,
        strict=True,
    ):
        session_window = session_windows.get(
            session_date
        )

        if session_window is None:
            keep_rows.append(False)
            continue

        market_open, market_close = (
            session_window
        )

        keep_rows.append(
            market_open
            <= timestamp
            < market_close
        )

    result["timestamp"] = timestamps

    return result.loc[
        keep_rows
    ].reset_index(drop=True)