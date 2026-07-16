"""Tests for the complete historical range-download pipeline."""

from datetime import date, datetime, timezone
import json
from pathlib import Path

import pandas as pd

import pytest

from trading_bot.config import (
    Settings,
    StrategySettings,
)
from trading_bot.data.date_ranges import (
    DateRangeChunk,
)
from trading_bot.data.download_range import (
    build_parser,
    run_range_download,
)
from trading_bot.data.range_audit import (
    RangeCoverageError,
)


def sample_settings() -> Settings:
    """Create settings containing fake credentials."""

    return Settings(
        alpaca_api_key="test-key",
        alpaca_secret_key="test-secret",
        symbol="SPY",
        timeframe_minutes=15,
        data_feed="iex",
        strategy=StrategySettings(
            fast_ema=9,
            slow_ema=21,
        ),
    )


def fake_complete_session(
    chunk: DateRangeChunk,
) -> pd.DataFrame:
    """Return one complete NYSE session for January 2, 2024."""

    requested_session = date(2024, 1, 2)

    if not (
        chunk.start.date()
        <= requested_session
        < chunk.end.date()
    ):
        return pd.DataFrame()

    timestamps = pd.date_range(
        start="2024-01-02T14:30:00Z",
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


def test_complete_pipeline_creates_outputs(
    tmp_path: Path,
) -> None:
    generated_at = datetime(
        2026,
        7,
        16,
        12,
        0,
        tzinfo=timezone.utc,
    )

    result = run_range_download(
        settings=sample_settings(),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 2),
        output_directory=tmp_path,
        fetch_chunk=fake_complete_session,
        show_progress=False,
        generated_at_utc=generated_at,
    )

    assert result.audited.session_count == 1
    assert result.audited.actual_bar_count == 26
    assert result.audited.expected_bar_count == 26
    assert result.audited.missing_bar_count == 0
    assert result.audited.unexpected_bar_count == 0

    assert result.paths.bars.exists()
    assert result.paths.coverage.exists()
    assert result.paths.metadata.exists()


def test_pipeline_output_names_match_range(
    tmp_path: Path,
) -> None:
    result = run_range_download(
        settings=sample_settings(),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 2),
        output_directory=tmp_path,
        fetch_chunk=fake_complete_session,
        show_progress=False,
    )

    assert result.paths.bars.name == (
        "SPY_15min_2024-01-01_"
        "2024-01-02.parquet"
    )


def test_pipeline_metadata_matches_saved_data(
    tmp_path: Path,
) -> None:
    result = run_range_download(
        settings=sample_settings(),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 2),
        output_directory=tmp_path,
        fetch_chunk=fake_complete_session,
        show_progress=False,
    )

    metadata = json.loads(
        result.paths.metadata.read_text(
            encoding="utf-8"
        )
    )

    assert metadata["symbol"] == "SPY"
    assert metadata["row_count"] == 26
    assert metadata["session_count"] == 1
    assert metadata["missing_bar_count"] == 0
    assert metadata["unexpected_bar_count"] == 0


def test_pipeline_saved_bars_reload_correctly(
    tmp_path: Path,
) -> None:
    result = run_range_download(
        settings=sample_settings(),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 2),
        output_directory=tmp_path,
        fetch_chunk=fake_complete_session,
        show_progress=False,
    )

    reloaded = pd.read_parquet(
        result.paths.bars
    )

    assert len(reloaded) == 26

    assert reloaded[
        "timestamp"
    ].is_monotonic_increasing


def test_pipeline_does_not_modify_fake_source_frame(
    tmp_path: Path,
) -> None:
    source_frame = fake_complete_session(
        DateRangeChunk(
            start=datetime(
                2024,
                1,
                1,
                tzinfo=timezone.utc,
            ),
            end=datetime(
                2024,
                2,
                1,
                tzinfo=timezone.utc,
            ),
        )
    )

    source_copy = source_frame.copy(
        deep=True
    )

    def return_source(
        chunk: DateRangeChunk,
    ) -> pd.DataFrame:
        return source_frame

    run_range_download(
        settings=sample_settings(),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 2),
        output_directory=tmp_path,
        fetch_chunk=return_source,
        show_progress=False,
    )

    pd.testing.assert_frame_equal(
        source_frame,
        source_copy,
    )
def fake_complete_and_incomplete_sessions(
    chunk: DateRangeChunk,
) -> pd.DataFrame:
    """Return one complete session and one incomplete session."""

    frames: list[pd.DataFrame] = []

    january_second = date(2024, 1, 2)

    if (
        chunk.start.date()
        <= january_second
        < chunk.end.date()
    ):
        timestamps = pd.date_range(
            start="2024-01-02T14:30:00Z",
            periods=26,
            freq="15min",
        )

        frames.append(
            pd.DataFrame(
                {
                    "symbol": ["SPY"] * 26,
                    "timestamp": timestamps,
                    "open": [100.0] * 26,
                    "high": [101.0] * 26,
                    "low": [99.0] * 26,
                    "close": [100.5] * 26,
                    "volume": [1000] * 26,
                }
            )
        )

    january_third = date(2024, 1, 3)

    if (
        chunk.start.date()
        <= january_third
        < chunk.end.date()
    ):
        timestamps = pd.date_range(
            start="2024-01-03T14:30:00Z",
            periods=26,
            freq="15min",
        ).delete(5)

        frames.append(
            pd.DataFrame(
                {
                    "symbol": ["SPY"] * 25,
                    "timestamp": timestamps,
                    "open": [101.0] * 25,
                    "high": [102.0] * 25,
                    "low": [100.0] * 25,
                    "close": [101.5] * 25,
                    "volume": [1100] * 25,
                }
            )
        )

    if not frames:
        return pd.DataFrame()

    return pd.concat(
        frames,
        ignore_index=True,
    )


def test_incomplete_session_is_strict_by_default(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        RangeCoverageError,
        match="1 missing bars",
    ):
        run_range_download(
            settings=sample_settings(),
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 3),
            output_directory=tmp_path,
            fetch_chunk=(
                fake_complete_and_incomplete_sessions
            ),
            show_progress=False,
        )


def test_explicit_exclusion_is_saved_in_metadata(
    tmp_path: Path,
) -> None:
    result = run_range_download(
        settings=sample_settings(),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 3),
        output_directory=tmp_path,
        exclude_incomplete_sessions=True,
        fetch_chunk=(
            fake_complete_and_incomplete_sessions
        ),
        show_progress=False,
    )

    metadata = json.loads(
        result.paths.metadata.read_text(
            encoding="utf-8"
        )
    )

    assert result.audited.excluded_session_dates == (
        date(2024, 1, 3),
    )

    assert metadata[
        "requested_session_count"
    ] == 2

    assert metadata["session_count"] == 1

    assert metadata[
        "excluded_session_count"
    ] == 1

    assert metadata[
        "excluded_session_dates"
    ] == [
        "2024-01-03"
    ]

    assert metadata[
        "excluded_missing_bar_count"
    ] == 1

    assert metadata[
        "requested_expected_bar_count"
    ] == 52

    assert metadata[
        "expected_bar_count"
    ] == 26


def test_parser_accepts_exclusion_flag() -> None:
    arguments = build_parser().parse_args(
        [
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-03",
            "--exclude-incomplete-sessions",
        ]
    )

    assert (
        arguments.exclude_incomplete_sessions
        is True
    )