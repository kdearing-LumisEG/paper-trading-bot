"""Tests for historical-download date range generation."""

from datetime import date, datetime, timezone

import pytest

from trading_bot.data.date_ranges import (
    DateRangeChunk,
    build_monthly_chunks,
    parse_date_range,
    parse_iso_date,
)


def test_parse_iso_date() -> None:
    result = parse_iso_date(
        "2024-01-15",
        field_name="start",
    )

    assert result == date(2024, 1, 15)


@pytest.mark.parametrize(
    ("value", "expected_message"),
    [
        ("", "start cannot be empty"),
        ("01-15-2024", "start must use YYYY-MM-DD"),
        ("2024-13-01", "start must use YYYY-MM-DD"),
        ("not-a-date", "start must use YYYY-MM-DD"),
    ],
)
def test_invalid_dates_fail_clearly(
    value: str,
    expected_message: str,
) -> None:
    with pytest.raises(
        ValueError,
        match=expected_message,
    ):
        parse_iso_date(
            value,
            field_name="start",
        )


@pytest.mark.parametrize(
    ("start_value", "end_value"),
    [
        ("2024-01-01", "2024-01-01"),
        ("2024-02-01", "2024-01-01"),
    ],
)
def test_start_must_occur_before_end(
    start_value: str,
    end_value: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="start must occur before end",
    ):
        parse_date_range(
            start_value,
            end_value,
        )


def test_partial_months_are_bounded_correctly() -> None:
    chunks = build_monthly_chunks(
        start_date=date(2024, 1, 15),
        end_date=date(2024, 3, 10),
    )

    assert chunks == [
        DateRangeChunk(
            start=datetime(
                2024,
                1,
                15,
                tzinfo=timezone.utc,
            ),
            end=datetime(
                2024,
                2,
                1,
                tzinfo=timezone.utc,
            ),
        ),
        DateRangeChunk(
            start=datetime(
                2024,
                2,
                1,
                tzinfo=timezone.utc,
            ),
            end=datetime(
                2024,
                3,
                1,
                tzinfo=timezone.utc,
            ),
        ),
        DateRangeChunk(
            start=datetime(
                2024,
                3,
                1,
                tzinfo=timezone.utc,
            ),
            end=datetime(
                2024,
                3,
                11,
                tzinfo=timezone.utc,
            ),
        ),
    ]


def test_chunks_have_no_gaps_or_overlaps() -> None:
    chunks = build_monthly_chunks(
        start_date=date(2024, 1, 15),
        end_date=date(2024, 6, 20),
    )

    for previous_chunk, next_chunk in zip(
        chunks,
        chunks[1:],
    ):
        assert previous_chunk.end == next_chunk.start


def test_chunk_boundaries_are_utc() -> None:
    chunks = build_monthly_chunks(
        start_date=date(2024, 1, 1),
        end_date=date(2024, 2, 29),
    )

    for chunk in chunks:
        assert chunk.start.tzinfo == timezone.utc
        assert chunk.end.tzinfo == timezone.utc


def test_target_research_range_creates_30_chunks() -> None:
    chunks = build_monthly_chunks(
        start_date=date(2024, 1, 1),
        end_date=date(2026, 6, 30),
    )

    assert len(chunks) == 30

    assert chunks[0].start == datetime(
        2024,
        1,
        1,
        tzinfo=timezone.utc,
    )

    assert chunks[-1].end == datetime(
        2026,
        7,
        1,
        tzinfo=timezone.utc,
    )


def test_date_range_chunk_rejects_invalid_boundaries() -> None:
    boundary = datetime(
        2024,
        1,
        1,
        tzinfo=timezone.utc,
    )

    with pytest.raises(
        ValueError,
        match="Chunk start must occur before chunk end",
    ):
        DateRangeChunk(
            start=boundary,
            end=boundary,
        )