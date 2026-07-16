"""Tests for historical dataset output and metadata."""

from datetime import date, datetime, timezone
import json
from pathlib import Path

import pandas as pd
import pytest

from trading_bot.data.coverage import (
    SessionCoverageAudit,
)
from trading_bot.data.range_audit import (
    AuditedRange,
)
from trading_bot.data.range_output import (
    RangeOutputError,
    build_dataset_metadata,
    build_dataset_paths,
    save_audited_range,
)


def make_audited_range() -> AuditedRange:
    """Create a small complete audited dataset."""

    frame = pd.DataFrame(
        {
            "symbol": ["SPY", "SPY"],
            "timestamp": pd.to_datetime(
                [
                    "2024-01-02T14:30:00Z",
                    "2024-01-02T14:45:00Z",
                ],
                utc=True,
            ),
            "open": [100.0, 100.5],
            "high": [101.0, 101.5],
            "low": [99.0, 100.0],
            "close": [100.5, 101.0],
            "volume": [1000, 1100],
        }
    )

    sessions = pd.DataFrame(
        {
            "session_date": [
                date(2024, 1, 2)
            ],
            "market_open": pd.to_datetime(
                [
                    "2024-01-02T14:30:00Z"
                ],
                utc=True,
            ),
            "market_close": pd.to_datetime(
                [
                    "2024-01-02T21:00:00Z"
                ],
                utc=True,
            ),
            "expected_bars": [2],
            "actual_bars": [2],
            "missing_bars": [0],
            "unexpected_bars": [0],
            "complete": [True],
        }
    )

    coverage = SessionCoverageAudit(
        sessions=sessions,
        missing_timestamps=pd.DatetimeIndex(
            [],
            tz="UTC",
        ),
        unexpected_timestamps=pd.DatetimeIndex(
            [],
            tz="UTC",
        ),
    )

    return AuditedRange(
        frame=frame,
        coverage=coverage,
        requested_start=datetime(
            2024,
            1,
            2,
            tzinfo=timezone.utc,
        ),
        requested_end_exclusive=datetime(
            2024,
            1,
            3,
            tzinfo=timezone.utc,
        ),
        merged_row_count=2,
        regular_session_row_count=2,
    )


def test_output_filenames_are_deterministic(
    tmp_path: Path,
) -> None:
    paths = build_dataset_paths(
        output_directory=tmp_path,
        symbol="spy",
        timeframe_minutes=15,
        start_date=date(2024, 1, 1),
        end_date=date(2026, 6, 30),
    )

    assert paths.bars.name == (
        "SPY_15min_2024-01-01_"
        "2026-06-30.parquet"
    )

    assert paths.coverage.name == (
        "SPY_15min_2024-01-01_"
        "2026-06-30_coverage.csv"
    )

    assert paths.metadata.name == (
        "SPY_15min_2024-01-01_"
        "2026-06-30_metadata.json"
    )
def test_single_day_output_filename_is_valid(
    tmp_path: Path,
) -> None:
    paths = build_dataset_paths(
        output_directory=tmp_path,
        symbol="SPY",
        timeframe_minutes=15,
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 2),
    )

    assert paths.bars.name == (
        "SPY_15min_2024-01-02_"
        "2024-01-02.parquet"
    )

def test_end_before_start_fails(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        RangeOutputError,
        match="start cannot occur after end",
    ):
        build_dataset_paths(
            output_directory=tmp_path,
            symbol="SPY",
            timeframe_minutes=15,
            start_date=date(2024, 1, 3),
            end_date=date(2024, 1, 2),
        )

def test_metadata_contains_required_fields() -> None:
    generated_at = datetime(
        2026,
        7,
        16,
        12,
        0,
        tzinfo=timezone.utc,
    )

    metadata = build_dataset_metadata(
        audited_range=make_audited_range(),
        symbol="SPY",
        timeframe_minutes=15,
        data_feed="iex",
        duplicate_rows_removed=3,
        generated_at_utc=generated_at,
    )

    assert metadata["symbol"] == "SPY"
    assert metadata["timeframe_minutes"] == 15
    assert metadata["data_feed"] == "iex"
    assert metadata["requested_start"] == "2024-01-02"
    assert metadata["requested_end"] == "2024-01-02"

    assert metadata[
        "actual_first_timestamp"
    ] == "2024-01-02T14:30:00+00:00"

    assert metadata[
        "actual_last_timestamp"
    ] == "2024-01-02T14:45:00+00:00"

    assert metadata["row_count"] == 2

    assert metadata[
        "requested_session_count"
    ] == 1

    assert metadata["session_count"] == 1

    assert metadata[
        "excluded_session_count"
    ] == 0

    assert metadata[
        "excluded_session_dates"
    ] == []

    assert metadata[
        "excluded_missing_bar_count"
    ] == 0

    assert metadata[
        "expected_bar_count"
    ] == 2

    assert metadata[
        "requested_expected_bar_count"
    ] == 2

    assert metadata["actual_bar_count"] == 2
    assert metadata["missing_bar_count"] == 0
    assert metadata["unexpected_bar_count"] == 0
    assert metadata["duplicate_rows_removed"] == 3
    assert metadata["price_adjustment"] == "raw"

    assert metadata[
        "regular_session_filter_applied"
    ] is True


def test_save_creates_all_output_files(
    tmp_path: Path,
) -> None:
    paths = save_audited_range(
        audited_range=make_audited_range(),
        output_directory=tmp_path,
        symbol="SPY",
        timeframe_minutes=15,
        data_feed="iex",
        duplicate_rows_removed=0,
    )

    assert paths.bars.exists()
    assert paths.coverage.exists()
    assert paths.metadata.exists()

    saved_bars = pd.read_parquet(
        paths.bars
    )

    assert len(saved_bars) == 2

    saved_coverage = pd.read_csv(
        paths.coverage
    )

    assert len(saved_coverage) == 1

    metadata = json.loads(
        paths.metadata.read_text(
            encoding="utf-8"
        )
    )

    assert metadata["row_count"] == 2


def test_existing_files_are_not_overwritten(
    tmp_path: Path,
) -> None:
    audited_range = make_audited_range()

    save_audited_range(
        audited_range=audited_range,
        output_directory=tmp_path,
        symbol="SPY",
        timeframe_minutes=15,
        data_feed="iex",
        duplicate_rows_removed=0,
    )

    with pytest.raises(
        FileExistsError,
        match="Refusing to overwrite",
    ):
        save_audited_range(
            audited_range=audited_range,
            output_directory=tmp_path,
            symbol="SPY",
            timeframe_minutes=15,
            data_feed="iex",
            duplicate_rows_removed=0,
        )


def test_overwrite_true_replaces_files(
    tmp_path: Path,
) -> None:
    audited_range = make_audited_range()

    paths = save_audited_range(
        audited_range=audited_range,
        output_directory=tmp_path,
        symbol="SPY",
        timeframe_minutes=15,
        data_feed="iex",
        duplicate_rows_removed=0,
    )

    changed_range = make_audited_range()

    changed_range.frame.loc[
        0,
        "close",
    ] = 777.0

    save_audited_range(
        audited_range=changed_range,
        output_directory=tmp_path,
        symbol="SPY",
        timeframe_minutes=15,
        data_feed="iex",
        duplicate_rows_removed=0,
        overwrite=True,
    )

    reloaded = pd.read_parquet(
        paths.bars
    )

    assert reloaded.loc[
        0,
        "close",
    ] == 777.0


def test_source_dataframe_is_not_modified(
    tmp_path: Path,
) -> None:
    audited_range = make_audited_range()

    original = audited_range.frame.copy(
        deep=True
    )

    save_audited_range(
        audited_range=audited_range,
        output_directory=tmp_path,
        symbol="SPY",
        timeframe_minutes=15,
        data_feed="iex",
        duplicate_rows_removed=0,
    )

    pd.testing.assert_frame_equal(
        audited_range.frame,
        original,
    )


def test_generated_time_must_be_timezone_aware() -> None:
    with pytest.raises(
        RangeOutputError,
        match="must be timezone-aware",
    ):
        build_dataset_metadata(
            audited_range=make_audited_range(),
            symbol="SPY",
            timeframe_minutes=15,
            data_feed="iex",
            duplicate_rows_removed=0,
            generated_at_utc=datetime(
                2026,
                7,
                16,
                12,
                0,
            ),
        )