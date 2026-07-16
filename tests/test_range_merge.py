"""Tests for merging monthly historical-data chunks."""

from datetime import datetime, timezone

import pandas as pd
import pytest

from trading_bot.data.date_ranges import (
    DateRangeChunk,
)
from trading_bot.data.range_merge import (
    RangeMergeError,
    merge_fetched_chunks,
)
from trading_bot.data.range_source import (
    FetchedChunk,
)


def make_chunk(
    start_day: int,
    frame: pd.DataFrame,
) -> FetchedChunk:
    """Create a fetched chunk for January 2024."""

    start = datetime(
        2024,
        1,
        start_day,
        tzinfo=timezone.utc,
    )

    end = datetime(
        2024,
        1,
        start_day + 1,
        tzinfo=timezone.utc,
    )

    return FetchedChunk(
        chunk=DateRangeChunk(
            start=start,
            end=end,
        ),
        frame=frame,
    )


def make_bar(
    timestamp: str,
    close: float = 100.5,
) -> pd.DataFrame:
    """Create one valid SPY bar."""

    return pd.DataFrame(
        {
            "symbol": ["spy"],
            "timestamp": [timestamp],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [close],
            "volume": [1000],
        }
    )


def test_chunks_merge_and_sort_by_timestamp() -> None:
    later = make_chunk(
        2,
        make_bar(
            "2024-01-02T14:45:00Z"
        ),
    )

    earlier = make_chunk(
        1,
        make_bar(
            "2024-01-02T14:30:00Z"
        ),
    )

    result = merge_fetched_chunks(
        fetched_chunks=[
            later,
            earlier,
        ],
        expected_symbol="SPY",
        timeframe_minutes=15,
    )

    assert result.frame[
        "timestamp"
    ].tolist() == [
        pd.Timestamp(
            "2024-01-02T14:30:00Z"
        ),
        pd.Timestamp(
            "2024-01-02T14:45:00Z"
        ),
    ]

    assert result.frame[
        "symbol"
    ].tolist() == [
        "SPY",
        "SPY",
    ]


def test_identical_duplicates_are_removed() -> None:
    frame = make_bar(
        "2024-01-02T14:30:00Z"
    )

    result = merge_fetched_chunks(
        fetched_chunks=[
            make_chunk(
                1,
                frame,
            ),
            make_chunk(
                2,
                frame.copy(deep=True),
            ),
        ],
        expected_symbol="SPY",
        timeframe_minutes=15,
    )

    assert len(result.frame) == 1
    assert (
        result.duplicate_rows_removed
        == 1
    )


def test_conflicting_duplicates_fail() -> None:
    first = make_bar(
        "2024-01-02T14:30:00Z",
        close=100.5,
    )

    conflicting = make_bar(
        "2024-01-02T14:30:00Z",
        close=105.0,
    )

    with pytest.raises(
        RangeMergeError,
        match="Conflicting duplicate bars",
    ):
        merge_fetched_chunks(
            fetched_chunks=[
                make_chunk(1, first),
                make_chunk(
                    2,
                    conflicting,
                ),
            ],
            expected_symbol="SPY",
            timeframe_minutes=15,
        )


def test_empty_chunks_are_ignored() -> None:
    result = merge_fetched_chunks(
        fetched_chunks=[
            make_chunk(
                1,
                pd.DataFrame(),
            ),
            make_chunk(
                2,
                make_bar(
                    "2024-01-02T14:30:00Z"
                ),
            ),
        ],
        expected_symbol="SPY",
        timeframe_minutes=15,
    )

    assert len(result.frame) == 1
    assert result.source_chunk_count == 2
    assert result.nonempty_chunk_count == 1


def test_all_empty_chunks_fail() -> None:
    with pytest.raises(
        RangeMergeError,
        match="All fetched chunks were empty",
    ):
        merge_fetched_chunks(
            fetched_chunks=[
                make_chunk(
                    1,
                    pd.DataFrame(),
                ),
            ],
            expected_symbol="SPY",
            timeframe_minutes=15,
        )


def test_missing_required_columns_fail() -> None:
    invalid_frame = make_bar(
        "2024-01-02T14:30:00Z"
    ).drop(
        columns=["volume"]
    )

    with pytest.raises(
        RangeMergeError,
        match="missing required columns: volume",
    ):
        merge_fetched_chunks(
            fetched_chunks=[
                make_chunk(
                    1,
                    invalid_frame,
                ),
            ],
            expected_symbol="SPY",
            timeframe_minutes=15,
        )


def test_source_frames_are_not_modified() -> None:
    source_frame = make_bar(
        "2024-01-02T14:30:00Z"
    )

    original_copy = source_frame.copy(
        deep=True
    )

    merge_fetched_chunks(
        fetched_chunks=[
            make_chunk(
                1,
                source_frame,
            ),
        ],
        expected_symbol="SPY",
        timeframe_minutes=15,
    )

    pd.testing.assert_frame_equal(
        source_frame,
        original_copy,
    )
    