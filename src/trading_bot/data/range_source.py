"""Chunked historical-bar retrieval for explicit date ranges."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import pandas as pd
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from trading_bot.config import Settings
from trading_bot.data.date_ranges import (
    DateRangeChunk,
    build_monthly_chunks,
)


class RangeSourceError(ValueError):
    """Raised when chunked historical retrieval fails validation."""


@dataclass
class FetchedChunk:
    """Market data returned for one requested date-range chunk."""

    chunk: DateRangeChunk
    frame: pd.DataFrame


ChunkFetcher = Callable[[DateRangeChunk], pd.DataFrame]

ProgressCallback = Callable[
    [int, int, DateRangeChunk],
    None,
]


def _resolve_data_feed(feed_name: str) -> DataFeed:
    """Convert the configured feed name into Alpaca's enum."""

    feeds = {
        "iex": DataFeed.IEX,
        "sip": DataFeed.SIP,
    }

    normalized_name = feed_name.strip().lower()

    try:
        return feeds[normalized_name]
    except KeyError as exc:
        raise RangeSourceError(
            f"Unsupported Alpaca data feed: {feed_name}"
        ) from exc


def _make_alpaca_chunk_fetcher(
    settings: Settings,
) -> ChunkFetcher:
    """Create a read-only Alpaca fetcher that reuses one client."""

    client = StockHistoricalDataClient(
        api_key=settings.alpaca_api_key,
        secret_key=settings.alpaca_secret_key,
    )

    feed = _resolve_data_feed(
        settings.data_feed
    )

    timeframe = TimeFrame(
        settings.timeframe_minutes,
        TimeFrameUnit.Minute,
    )

    def fetch_chunk(
        chunk: DateRangeChunk,
    ) -> pd.DataFrame:
        """Retrieve bars for one exclusive-end interval."""

        request = StockBarsRequest(
            symbol_or_symbols=settings.symbol,
            timeframe=timeframe,
            start=chunk.start,
            end=chunk.end,
            adjustment=Adjustment.RAW,
            feed=feed,
        )

        response = client.get_stock_bars(
            request
        )

        return response.df.reset_index()

    return fetch_chunk


def fetch_bars_by_month(
    settings: Settings,
    start_date: date,
    end_date: date,
    fetch_chunk: ChunkFetcher | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[FetchedChunk]:
    """Retrieve one dataframe for each monthly date-range chunk.

    The returned dataframes are not merged, sorted, validated, or saved.
    Those operations belong to later pipeline stages.

    A custom fetch_chunk callable can be supplied for testing so tests
    never need to contact Alpaca.
    """

    chunks = build_monthly_chunks(
        start_date=start_date,
        end_date=end_date,
    )

    active_fetcher = (
        fetch_chunk
        if fetch_chunk is not None
        else _make_alpaca_chunk_fetcher(settings)
    )

    results: list[FetchedChunk] = []
    total_chunks = len(chunks)

    for chunk_number, chunk in enumerate(
        chunks,
        start=1,
    ):
        if progress_callback is not None:
            progress_callback(
                chunk_number,
                total_chunks,
                chunk,
            )

        frame = active_fetcher(chunk)

        if not isinstance(frame, pd.DataFrame):
            raise TypeError(
                "Chunk fetcher must return a pandas DataFrame."
            )

        results.append(
            FetchedChunk(
                chunk=chunk,
                frame=frame.copy(deep=True),
            )
        )

    return results