"""Recent stock-bar retrieval for one-shot strategy evaluation."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

import pandas as pd
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit


class RecentBarSource(Protocol):
    """Source of recent bars for one symbol."""

    def fetch_bars(
        self,
        *,
        symbol: str,
        timeframe_minutes: int,
        start: datetime,
        end: datetime,
        data_feed: str,
    ) -> pd.DataFrame:
        """Return recent bars as a dataframe."""


def _resolve_data_feed(
    feed_name: str,
) -> DataFeed:
    feeds = {
        "iex": DataFeed.IEX,
        "sip": DataFeed.SIP,
    }

    try:
        return feeds[feed_name]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported Alpaca data feed: {feed_name}"
        ) from exc


class AlpacaRecentBarSource:
    """Read recent stock bars from Alpaca's market-data API."""

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        data_client: StockHistoricalDataClient | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError(
                "api_key cannot be empty."
            )

        if not secret_key.strip():
            raise ValueError(
                "secret_key cannot be empty."
            )

        self._client = (
            data_client
            if data_client is not None
            else StockHistoricalDataClient(
                api_key=api_key,
                secret_key=secret_key,
            )
        )

    def fetch_bars(
        self,
        *,
        symbol: str,
        timeframe_minutes: int,
        start: datetime,
        end: datetime,
        data_feed: str,
    ) -> pd.DataFrame:
        """Fetch recent bars without submitting orders."""

        if timeframe_minutes <= 0:
            raise ValueError(
                "timeframe_minutes must be positive."
            )

        if start >= end:
            raise ValueError(
                "start must be before end."
            )

        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame(
                timeframe_minutes,
                TimeFrameUnit.Minute,
            ),
            start=start,
            end=end,
            adjustment=Adjustment.RAW,
            feed=_resolve_data_feed(
                data_feed
            ),
        )

        response = self._client.get_stock_bars(
            request
        )

        frame = response.df.reset_index()

        return frame.copy(deep=True)
