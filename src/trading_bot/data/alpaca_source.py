"""Read-only adapter for retrieving historical stock bars from Alpaca."""

from datetime import datetime, time, timedelta, timezone

import pandas as pd
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from trading_bot.config import Settings, load_settings


def _resolve_data_feed(feed_name: str) -> DataFeed:
    """Convert our configuration value into Alpaca's feed enum."""

    feeds = {
        "iex": DataFeed.IEX,
        "sip": DataFeed.SIP,
    }

    try:
        return feeds[feed_name]
    except KeyError as exc:
        raise ValueError(f"Unsupported Alpaca data feed: {feed_name}") from exc


def _completed_data_window(
    lookback_calendar_days: int,
) -> tuple[datetime, datetime]:
    """Create a UTC window that excludes the current calendar day."""

    if lookback_calendar_days <= 0:
        raise ValueError("lookback_calendar_days must be positive.")

    today_utc = datetime.now(timezone.utc).date()
    end = datetime.combine(
        today_utc,
        time.min,
        tzinfo=timezone.utc,
    )
    start = end - timedelta(days=lookback_calendar_days)

    return start, end


def fetch_recent_bars(
    settings: Settings,
    lookback_calendar_days: int = 14,
) -> pd.DataFrame:
    """Retrieve recent historical bars without submitting any orders."""

    start, end = _completed_data_window(lookback_calendar_days)

    client = StockHistoricalDataClient(
        api_key=settings.alpaca_api_key,
        secret_key=settings.alpaca_secret_key,
    )

    request = StockBarsRequest(
        symbol_or_symbols=settings.symbol,
        timeframe=TimeFrame(
            settings.timeframe_minutes,
            TimeFrameUnit.Minute,
        ),
        start=start,
        end=end,
        adjustment=Adjustment.RAW,
        feed=_resolve_data_feed(settings.data_feed),
    )

    response = client.get_stock_bars(request)
    frame = response.df.reset_index()

    if frame.empty:
        raise ValueError(
            f"Alpaca returned no bars for {settings.symbol} "
            f"between {start.isoformat()} and {end.isoformat()}."
        )

    required_columns = {
        "symbol",
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
    }

    missing_columns = required_columns.difference(frame.columns)

    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Alpaca response is missing columns: {missing}")

    return frame


def main() -> None:
    """Run a safe market-data connectivity check."""

    settings = load_settings()
    bars = fetch_recent_bars(settings)

    print("Read-only Alpaca market-data request succeeded.")
    print(f"Symbol: {settings.symbol}")
    print(f"Feed: {settings.data_feed}")
    print(f"Timeframe: {settings.timeframe_minutes} minutes")
    print(f"Rows received: {len(bars)}")
    print(f"First timestamp: {bars['timestamp'].min()}")
    print(f"Last timestamp: {bars['timestamp'].max()}")
    print()
    print("First three bars:")
    print(bars.head(3).to_string(index=False))


if __name__ == "__main__":
    main()
