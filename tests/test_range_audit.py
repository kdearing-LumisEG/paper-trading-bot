"""Tests for full-range exchange-session coverage auditing."""

from datetime import date

import pandas as pd
import pytest

from trading_bot.data.range_audit import (
    RangeCoverageError,
    audit_merged_range,
)
from trading_bot.data.range_merge import (
    MergedBars,
)


def make_session_bars(
    session_date: str,
) -> pd.DataFrame:
    """Create one complete 15-minute NYSE session.

    January NYSE hours are 14:30 through 21:00 UTC.
    The final 15-minute bar begins at 20:45 UTC.
    """

    timestamps = pd.date_range(
        start=f"{session_date}T14:30:00Z",
        periods=26,
        freq="15min",
    )

    row_count = len(timestamps)

    return pd.DataFrame(
        {
            "symbol": ["SPY"] * row_count,
            "timestamp": timestamps,
            "open": [100.0] * row_count,
            "high": [101.0] * row_count,
            "low": [99.0] * row_count,
            "close": [100.5] * row_count,
            "volume": [1000] * row_count,
        }
    )


def make_merged(
    frame: pd.DataFrame,
) -> MergedBars:
    """Create a merged result for testing."""

    return MergedBars(
        frame=frame,
        source_chunk_count=1,
        nonempty_chunk_count=1,
        duplicate_rows_removed=0,
    )


def complete_two_day_frame() -> pd.DataFrame:
    """Create complete January 2 and January 3 sessions."""

    return pd.concat(
        [
            make_session_bars(
                "2024-01-02"
            ),
            make_session_bars(
                "2024-01-03"
            ),
        ],
        ignore_index=True,
    )


def test_complete_range_passes() -> None:
    result = audit_merged_range(
        merged_bars=make_merged(
            complete_two_day_frame()
        ),
        expected_symbol="SPY",
        timeframe_minutes=15,
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 3),
    )

    assert result.session_count == 2
    assert result.expected_bar_count == 52
    assert result.actual_bar_count == 52
    assert result.missing_bar_count == 0
    assert result.unexpected_bar_count == 0
    assert result.coverage.is_complete


def test_after_hours_bars_are_removed() -> None:
    regular_bars = (
        complete_two_day_frame()
    )

    after_hours_bar = pd.DataFrame(
        {
            "symbol": ["SPY"],
            "timestamp": pd.to_datetime(
                [
                    "2024-01-02T13:00:00Z"
                ],
                utc=True,
            ),
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1000],
        }
    )

    combined = pd.concat(
        [
            regular_bars,
            after_hours_bar,
        ],
        ignore_index=True,
    ).sort_values(
        "timestamp"
    ).reset_index(
        drop=True
    )

    result = audit_merged_range(
        merged_bars=make_merged(
            combined
        ),
        expected_symbol="SPY",
        timeframe_minutes=15,
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 3),
    )

    assert result.merged_row_count == 53
    assert result.regular_session_row_count == 52
    assert result.actual_bar_count == 52


def test_missing_regular_session_bar_fails() -> None:
    incomplete = (
        complete_two_day_frame()
        .drop(index=5)
        .reset_index(drop=True)
    )

    with pytest.raises(
        RangeCoverageError,
        match="1 missing bars",
    ):
        audit_merged_range(
            merged_bars=make_merged(
                incomplete
            ),
            expected_symbol="SPY",
            timeframe_minutes=15,
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 3),
        )


def test_holiday_bar_is_removed() -> None:
    regular_bars = complete_two_day_frame()

    holiday_bar = pd.DataFrame(
        {
            "symbol": ["SPY"],
            "timestamp": pd.to_datetime(
                ["2024-01-01T15:00:00Z"],
                utc=True,
            ),
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1000],
        }
    )

    combined = pd.concat(
        [
            holiday_bar,
            regular_bars,
        ],
        ignore_index=True,
    ).sort_values(
        "timestamp"
    ).reset_index(drop=True)

    result = audit_merged_range(
        merged_bars=make_merged(
            combined
        ),
        expected_symbol="SPY",
        timeframe_minutes=15,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 3),
    )

    assert result.merged_row_count == 53
    assert result.actual_bar_count == 52
    assert result.unexpected_bar_count == 0
    assert result.coverage.is_complete


def test_source_dataframe_is_not_modified() -> None:
    source = complete_two_day_frame()
    source_copy = source.copy(
        deep=True
    )

    audit_merged_range(
        merged_bars=make_merged(
            source
        ),
        expected_symbol="SPY",
        timeframe_minutes=15,
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 3),
    )

    pd.testing.assert_frame_equal(
        source,
        source_copy,
    )


def test_invalid_range_fails() -> None:
    with pytest.raises(
        ValueError,
        match="start must occur before end",
    ):
        audit_merged_range(
            merged_bars=make_merged(
                complete_two_day_frame()
            ),
            expected_symbol="SPY",
            timeframe_minutes=15,
            start_date=date(2024, 1, 3),
            end_date=date(2024, 1, 2),
        )


def test_empty_merged_data_fails() -> None:
    empty = pd.DataFrame()

    with pytest.raises(
        RangeCoverageError,
        match="Merged bar data cannot be empty",
    ):
        audit_merged_range(
            merged_bars=make_merged(
                empty
            ),
            expected_symbol="SPY",
            timeframe_minutes=15,
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 3),
        )
def test_incomplete_session_can_be_explicitly_excluded() -> None:
    incomplete = (
        complete_two_day_frame()
        .drop(index=5)
        .reset_index(drop=True)
    )

    result = audit_merged_range(
        merged_bars=make_merged(
            incomplete
        ),
        expected_symbol="SPY",
        timeframe_minutes=15,
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 3),
        exclude_incomplete_sessions=True,
    )

    assert result.requested_session_count == 2
    assert result.session_count == 1

    assert result.excluded_session_dates == (
        date(2024, 1, 2),
    )

    assert result.actual_bar_count == 26
    assert result.expected_bar_count == 26
    assert result.requested_expected_bar_count == 52

    assert result.missing_bar_count == 1
    assert result.excluded_missing_bar_count == 1
    assert result.unexpected_bar_count == 0

    remaining_dates = (
        pd.to_datetime(
            result.frame["timestamp"],
            utc=True,
        )
        .dt.tz_convert("America/New_York")
        .dt.date
    )

    assert set(remaining_dates) == {
        date(2024, 1, 3)
    }

    coverage_dates = pd.to_datetime(
        result.coverage.sessions[
            "session_date"
        ]
    ).dt.date

    excluded_row = (
        result.coverage.sessions.loc[
            coverage_dates
            == date(2024, 1, 2)
        ]
        .iloc[0]
    )

    assert not bool(
        excluded_row[
            "included_in_dataset"
        ]
    )

    assert excluded_row[
        "exclusion_reason"
    ] == "incomplete_source_session"


def test_exclusion_fails_when_every_session_is_incomplete() -> None:
    incomplete = (
        complete_two_day_frame()
        .drop(index=[5, 31])
        .reset_index(drop=True)
    )

    with pytest.raises(
        RangeCoverageError,
        match="All requested sessions are incomplete",
    ):
        audit_merged_range(
            merged_bars=make_merged(
                incomplete
            ),
            expected_symbol="SPY",
            timeframe_minutes=15,
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 3),
            exclude_incomplete_sessions=True,
        )