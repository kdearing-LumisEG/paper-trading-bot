"""Read-only adapter for retrieving historical stock bars from Alpaca."""

from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import pandas as pd
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from trading_bot.config import Settings, load_settings
from trading_bot.data.storage import load_bars, save_bars
from trading_bot.data.validation import (
    filter_regular_session_bars,
    validate_bars,
)


def _resolve_data_feed(feed_name: str) -> DataFeed:
    """Convert our configuration value into Alpaca's feed enum."""

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


def _completed_data_window(
    lookback_calendar_days: int,
) -> tuple[datetime, datetime]:
    """Create a UTC window that excludes the current calendar day."""

    if lookback_calendar_days <= 0:
        raise ValueError(
            "lookback_calendar_days must be positive."
        )

    today_utc = datetime.now(timezone.utc).date()

    end = datetime.combine(
        today_utc,
        time.min,
        tzinfo=timezone.utc,
    )

    start = end - timedelta(
        days=lookback_calendar_days
    )

    return start, end


def fetch_recent_bars(
    settings: Settings,
    lookback_calendar_days: int = 14,
) -> pd.DataFrame:
    """Retrieve historical bars without submitting orders."""

    start, end = _completed_data_window(
        lookback_calendar_days
    )

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
        feed=_resolve_data_feed(
            settings.data_feed
        ),
    )

    response = client.get_stock_bars(request)
    frame = response.df.reset_index()

    if frame.empty:
        raise ValueError(
            f"Alpaca returned no bars for "
            f"{settings.symbol}."
        )

    return frame


def main() -> None:
    """Download, validate, save, and reload market bars."""

    settings = load_settings()

    raw_bars = fetch_recent_bars(settings)

    validated_bars = validate_bars(
        raw_bars,
        expected_symbol=settings.symbol,
        timeframe_minutes=settings.timeframe_minutes,
    )

    session_bars = filter_regular_session_bars(
        validated_bars
    )

    if session_bars.empty:
        raise ValueError(
            "No regular-session bars remain after filtering."
        )

    output_path = Path(
        "data/processed"
    ) / (
        f"{settings.symbol}_"
        f"{settings.timeframe_minutes}min.parquet"
    )

    save_bars(
        session_bars,
        output_path,
    )

    reloaded_bars = validate_bars(
        load_bars(output_path),
        expected_symbol=settings.symbol,
        timeframe_minutes=settings.timeframe_minutes,
    )

    print("Historical-data pipeline succeeded.")
    print(f"Symbol: {settings.symbol}")
    print(f"Feed: {settings.data_feed}")
    print(
        f"Timeframe: "
        f"{settings.timeframe_minutes} minutes"
    )
    print(f"Raw rows received: {len(raw_bars)}")
    print(
        f"Regular-session rows saved: "
        f"{len(reloaded_bars)}"
    )
    print(f"File: {output_path.resolve()}")
    print(
        f"First timestamp: "
        f"{reloaded_bars['timestamp'].min()}"
    )
    print(
        f"Last timestamp: "
        f"{reloaded_bars['timestamp'].max()}"
    )


if __name__ == "__main__":
    main()
