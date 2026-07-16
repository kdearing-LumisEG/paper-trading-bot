"""Tests for the complete historical range-download pipeline."""

from datetime import date, datetime, timezone
import json
from pathlib import Path

import pandas as pd

from trading_bot.config import (
    Settings,
    StrategySettings,
)
from trading_bot.data.date_ranges import (
    DateRangeChunk,
)
from trading_bot.data.download_range import (
    run_range_download,
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