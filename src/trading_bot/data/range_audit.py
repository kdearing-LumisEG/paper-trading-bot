"""Regular-session filtering and coverage auditing for date ranges."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

import pandas as pd

from trading_bot.data.coverage import (
    SessionCoverageAudit,
    audit_session_coverage,
    filter_exchange_session_bars,
)
from trading_bot.data.range_merge import MergedBars
from trading_bot.data.validation import validate_bars


class RangeCoverageError(ValueError):
    """Raised when a historical date range has incomplete coverage."""


@dataclass(frozen=True)
class AuditedRange:
    """An audited dataset and its exchange-session coverage details."""

    frame: pd.DataFrame
    coverage: SessionCoverageAudit
    requested_start: datetime
    requested_end_exclusive: datetime
    merged_row_count: int
    regular_session_row_count: int
    excluded_session_dates: tuple[date, ...] = ()

    @property
    def requested_session_count(self) -> int:
        """Return all exchange sessions in the requested range."""

        return len(self.coverage.sessions)

    @property
    def session_count(self) -> int:
        """Return sessions retained in the final dataset."""

        return (
            self.requested_session_count
            - len(self.excluded_session_dates)
        )

    @property
    def expected_bar_count(self) -> int:
        """Return expected bars for sessions retained in the dataset."""

        sessions = self.coverage.sessions

        if "included_in_dataset" not in sessions.columns:
            return int(
                sessions["expected_bars"].sum()
            )

        included = sessions[
            "included_in_dataset"
        ].astype(bool)

        return int(
            sessions.loc[
                included,
                "expected_bars",
            ].sum()
        )

    @property
    def requested_expected_bar_count(self) -> int:
        """Return expected bars before incomplete sessions are removed."""

        return int(
            self.coverage.sessions[
                "expected_bars"
            ].sum()
        )

    @property
    def actual_bar_count(self) -> int:
        """Return bars retained in the final dataset."""

        return len(self.frame)

    @property
    def missing_bar_count(self) -> int:
        """Return missing bars detected before session exclusion."""

        return len(
            self.coverage.missing_timestamps
        )

    @property
    def unexpected_bar_count(self) -> int:
        """Return unexpected timestamps detected by the audit."""

        return len(
            self.coverage.unexpected_timestamps
        )

    @property
    def excluded_missing_bar_count(self) -> int:
        """Return missing bars belonging to excluded sessions."""

        if not self.excluded_session_dates:
            return 0

        sessions = self.coverage.sessions

        session_dates = pd.to_datetime(
            sessions["session_date"]
        ).dt.date

        excluded = session_dates.isin(
            self.excluded_session_dates
        )

        return int(
            sessions.loc[
                excluded,
                "missing_bars",
            ].sum()
        )


def _inclusive_date_boundaries(
    start_date: date,
    end_date: date,
) -> tuple[datetime, datetime]:
    """Convert inclusive dates into UTC start and exclusive end times."""

    if start_date >= end_date:
        raise ValueError(
            "start must occur before end."
        )

    start = datetime.combine(
        start_date,
        time.min,
        tzinfo=timezone.utc,
    )

    end_exclusive = datetime.combine(
        end_date + timedelta(days=1),
        time.min,
        tzinfo=timezone.utc,
    )

    return start, end_exclusive


def _annotate_coverage(
    coverage: SessionCoverageAudit,
    excluded_session_dates: tuple[date, ...],
) -> SessionCoverageAudit:
    """Mark which audited sessions are included in the dataset."""

    sessions = coverage.sessions.copy(
        deep=True
    )

    session_dates = pd.to_datetime(
        sessions["session_date"]
    ).dt.date

    excluded = session_dates.isin(
        excluded_session_dates
    )

    sessions["included_in_dataset"] = (
        ~excluded
    )

    sessions["exclusion_reason"] = ""

    sessions.loc[
        excluded,
        "exclusion_reason",
    ] = "incomplete_source_session"

    return SessionCoverageAudit(
        sessions=sessions,
        missing_timestamps=(
            coverage.missing_timestamps.copy()
        ),
        unexpected_timestamps=(
            coverage.unexpected_timestamps.copy()
        ),
    )


def _exclude_sessions(
    frame: pd.DataFrame,
    excluded_session_dates: tuple[date, ...],
) -> pd.DataFrame:
    """Remove complete rows belonging to explicitly excluded sessions."""

    timestamps = pd.to_datetime(
        frame["timestamp"],
        utc=True,
        errors="raise",
    )

    session_dates = (
        timestamps
        .dt.tz_convert("America/New_York")
        .dt.date
    )

    keep = ~session_dates.isin(
        excluded_session_dates
    )

    return frame.loc[
        keep
    ].reset_index(drop=True)


def audit_merged_range(
    merged_bars: MergedBars,
    expected_symbol: str,
    timeframe_minutes: int,
    start_date: date,
    end_date: date,
    exclude_incomplete_sessions: bool = False,
) -> AuditedRange:
    """Filter, validate, and audit a merged historical dataset.

    The start and end dates are inclusive.

    By default, incomplete sessions cause the audit to fail. When
    exclude_incomplete_sessions is true, every incomplete session is
    removed in full and recorded in the returned coverage report.
    """

    start, end_exclusive = (
        _inclusive_date_boundaries(
            start_date=start_date,
            end_date=end_date,
        )
    )

    if merged_bars.frame.empty:
        raise RangeCoverageError(
            "Merged bar data cannot be empty."
        )

    regular_session_bars = (
        filter_exchange_session_bars(
            merged_bars.frame
        )
    )

    if regular_session_bars.empty:
        raise RangeCoverageError(
            "No exchange-session bars remain after filtering."
        )

    validated_bars = validate_bars(
        regular_session_bars,
        expected_symbol=expected_symbol,
        timeframe_minutes=timeframe_minutes,
    )

    coverage = audit_session_coverage(
        frame=validated_bars,
        timeframe_minutes=timeframe_minutes,
        start=start,
        end=end_exclusive,
    )

    missing_count = len(
        coverage.missing_timestamps
    )

    unexpected_count = len(
        coverage.unexpected_timestamps
    )

    if unexpected_count > 0:
        raise RangeCoverageError(
            "Historical range failed coverage audit: "
            f"{missing_count} missing bars and "
            f"{unexpected_count} unexpected bars."
        )

    incomplete_sessions = (
        coverage.sessions.loc[
            ~coverage.sessions["complete"]
        ]
    )

    if (
        not incomplete_sessions.empty
        and not exclude_incomplete_sessions
    ):
        raise RangeCoverageError(
            "Historical range failed coverage audit: "
            f"{missing_count} missing bars and "
            f"{unexpected_count} unexpected bars."
        )

    excluded_session_dates: tuple[
        date,
        ...,
    ] = ()

    final_bars = validated_bars

    if not incomplete_sessions.empty:
        excluded_session_dates = tuple(
            pd.to_datetime(
                incomplete_sessions[
                    "session_date"
                ]
            )
            .dt.date
            .tolist()
        )

        final_bars = _exclude_sessions(
            frame=validated_bars,
            excluded_session_dates=(
                excluded_session_dates
            ),
        )

        if final_bars.empty:
            raise RangeCoverageError(
                "All requested sessions are incomplete; "
                "no bars remain after exclusion."
            )

        final_bars = validate_bars(
            final_bars,
            expected_symbol=expected_symbol,
            timeframe_minutes=timeframe_minutes,
        )

    annotated_coverage = _annotate_coverage(
        coverage=coverage,
        excluded_session_dates=(
            excluded_session_dates
        ),
    )

    return AuditedRange(
        frame=final_bars.copy(deep=True),
        coverage=annotated_coverage,
        requested_start=start,
        requested_end_exclusive=(
            end_exclusive
        ),
        merged_row_count=len(
            merged_bars.frame
        ),
        regular_session_row_count=len(
            validated_bars
        ),
        excluded_session_dates=(
            excluded_session_dates
        ),
    )
