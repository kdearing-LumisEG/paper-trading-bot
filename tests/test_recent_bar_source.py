"""Tests for recent Alpaca bar retrieval."""

from datetime import datetime, timezone
from types import SimpleNamespace

from alpaca.data.enums import DataFeed
import pandas as pd

from trading_bot.runtime.market_data import (
    AlpacaRecentBarSource,
)


class FakeDataClient:
    def __init__(self) -> None:
        self.request = None

    def get_stock_bars(self, request):
        self.request = request

        index = pd.MultiIndex.from_tuples(
            [
                (
                    "SPY",
                    pd.Timestamp(
                        "2026-01-02T14:30:00Z"
                    ),
                )
            ],
            names=[
                "symbol",
                "timestamp",
            ],
        )

        frame = pd.DataFrame(
            {
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "volume": [1000],
                "trade_count": [10],
                "vwap": [100.25],
            },
            index=index,
        )

        return SimpleNamespace(
            df=frame
        )


def test_recent_source_builds_stock_bar_request() -> None:
    client = FakeDataClient()

    source = AlpacaRecentBarSource(
        api_key="key",
        secret_key="secret",
        data_client=client,  # type: ignore[arg-type]
    )

    start = datetime(
        2026,
        1,
        1,
        tzinfo=timezone.utc,
    )

    end = datetime(
        2026,
        1,
        2,
        16,
        0,
        tzinfo=timezone.utc,
    )

    result = source.fetch_bars(
        symbol="SPY",
        timeframe_minutes=15,
        start=start,
        end=end,
        data_feed="iex",
    )

    assert result.loc[0, "symbol"] == "SPY"
    assert result.loc[0, "close"] == 100.5
    assert client.request.symbol_or_symbols == "SPY"
    assert client.request.feed is DataFeed.IEX
    assert client.request.start == start.replace(
        tzinfo=None
    )
    assert client.request.end == end.replace(
        tzinfo=None
    )
