"""Regular-session filtering and coverage auditing for date ranges."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

import pandas as pd

from trading_bot.data.coverage import (
    SessionCoverageAudit,
    audit_session_coverage,
)
from trading_bot.data.range_merge import MergedBars
from trading_bot.data.validation import (
    filter_regular_session_bars,
    validate_bars,
)


class RangeCoverageError(ValueError):
    """Raised when a historical date range has incomplete coverage."""


@dataclass(frozen=True)
class AuditedRange:
    """A regular-session dataset with its exchange-calendar audit."""

    frame: pd.DataFrame
    coverage: SessionCoverageAudit
    requested_start: datetime
    requested_end_exclusive: datetime
    merged_row_count: int
    regular_session_row_count: int

    @property
    def session_count(self) -> int:
        """Return the number of expected exchange sessions."""

        return len(self.coverage.sessions)

    @property
    def expected_bar_count(self) -> int:
        """Return the total expected number of bars."""

        return int(
            self.coverage.sessions[
                "expected_bars"
            ].sum()
        )

    @property
    def actual_bar_count(self) -> int:
        """Return the total number of regular-session bars."""

        return len(self.frame)

    @property
    def missing_bar_count(self) -> int:
        """Return the number of missing expected timestamps."""

        return len(
            self.coverage.missing_timestamps
        )

    @property
    def unexpected_bar_count(self) -> int:
        """Return the number of unexpected timestamps."""

        return len(
            self.coverage.unexpected_timestamps
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


def audit_merged_range(
    merged_bars: MergedBars,
    expected_symbol: str,
    timeframe_minutes: int,
    start_date: date,
    end_date: date,
) -> AuditedRange:
    """Filter, validate, and audit a merged historical dataset.

    The caller-facing start and end dates are inclusive.
    The coverage audit receives an exclusive UTC end boundary.
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
        filter_regular_session_bars(
            merged_bars.frame
        )
    )

    if regular_session_bars.empty:
        raise RangeCoverageError(
            "No regular-session bars remain after filtering."
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

    if not coverage.is_complete:
        missing_count = len(
            coverage.missing_timestamps
        )

        unexpected_count = len(
            coverage.unexpected_timestamps
        )

        raise RangeCoverageError(
            "Historical range failed coverage audit: "
            f"{missing_count} missing bars and "
            f"{unexpected_count} unexpected bars."
        )

    return AuditedRange(
        frame=validated_bars.copy(
            deep=True
        ),
        coverage=coverage,
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
    )