"""Tests for chunked historical market-data retrieval."""

from datetime import date

import pandas as pd
import pytest

from trading_bot.config import (
    Settings,
    StrategySettings,
)
from trading_bot.data.date_ranges import (
    DateRangeChunk,
)
from trading_bot.data.range_source import (
    fetch_bars_by_month,
)


def sample_settings() -> Settings:
    """Create safe settings containing fake credentials."""

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


def sample_frame(
    chunk: DateRangeChunk,
) -> pd.DataFrame:
    """Create one deterministic fake bar for a chunk."""

    return pd.DataFrame(
        {
            "symbol": ["SPY"],
            "timestamp": [chunk.start],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1000],
        }
    )


def test_fetcher_receives_every_monthly_chunk() -> None:
    received_chunks: list[DateRangeChunk] = []

    def fake_fetcher(
        chunk: DateRangeChunk,
    ) -> pd.DataFrame:
        received_chunks.append(chunk)
        return sample_frame(chunk)

    results = fetch_bars_by_month(
        settings=sample_settings(),
        start_date=date(2024, 1, 15),
        end_date=date(2024, 3, 10),
        fetch_chunk=fake_fetcher,
    )

    assert len(results) == 3
    assert len(received_chunks) == 3

    assert received_chunks[0].start.isoformat() == (
        "2024-01-15T00:00:00+00:00"
    )
    assert received_chunks[0].end.isoformat() == (
        "2024-02-01T00:00:00+00:00"
    )

    assert received_chunks[-1].start.isoformat() == (
        "2024-03-01T00:00:00+00:00"
    )
    assert received_chunks[-1].end.isoformat() == (
        "2024-03-11T00:00:00+00:00"
    )


def test_chunk_results_preserve_boundaries() -> None:
    def fake_fetcher(
        chunk: DateRangeChunk,
    ) -> pd.DataFrame:
        return sample_frame(chunk)

    results = fetch_bars_by_month(
        settings=sample_settings(),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 2, 29),
        fetch_chunk=fake_fetcher,
    )

    assert len(results) == 2

    assert results[0].chunk.end == (
        results[1].chunk.start
    )


def test_empty_chunk_dataframes_are_preserved() -> None:
    def fake_fetcher(
        chunk: DateRangeChunk,
    ) -> pd.DataFrame:
        return pd.DataFrame()

    results = fetch_bars_by_month(
        settings=sample_settings(),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 2, 1),
        fetch_chunk=fake_fetcher,
    )

    assert len(results) == 2
    assert all(
        result.frame.empty
        for result in results
    )


def test_fetcher_must_return_dataframe() -> None:
    def invalid_fetcher(
        chunk: DateRangeChunk,
    ) -> str:
        return chunk.start.isoformat()

    with pytest.raises(
        TypeError,
        match="must return a pandas DataFrame",
    ):
        fetch_bars_by_month(
            settings=sample_settings(),
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            fetch_chunk=invalid_fetcher,  # type: ignore[arg-type]
        )


def test_returned_frames_are_defensive_copies() -> None:
    source_frames: list[pd.DataFrame] = []

    def fake_fetcher(
        chunk: DateRangeChunk,
    ) -> pd.DataFrame:
        frame = sample_frame(chunk)
        source_frames.append(frame)
        return frame

    results = fetch_bars_by_month(
        settings=sample_settings(),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        fetch_chunk=fake_fetcher,
    )

    results[0].frame.loc[
        0,
        "close",
    ] = 999.0

    assert source_frames[0].loc[
        0,
        "close",
    ] == 100.5


def test_progress_callback_reports_each_chunk() -> None:
    progress_events: list[
        tuple[int, int, DateRangeChunk]
    ] = []

    def fake_fetcher(
        chunk: DateRangeChunk,
    ) -> pd.DataFrame:
        return sample_frame(chunk)

    def record_progress(
        current: int,
        total: int,
        chunk: DateRangeChunk,
    ) -> None:
        progress_events.append(
            (current, total, chunk)
        )

    fetch_bars_by_month(
        settings=sample_settings(),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 3, 31),
        fetch_chunk=fake_fetcher,
        progress_callback=record_progress,
    )

    assert len(progress_events) == 3

    assert [
        event[0]
        for event in progress_events
    ] == [1, 2, 3]

    assert all(
        event[1] == 3
        for event in progress_events
    )