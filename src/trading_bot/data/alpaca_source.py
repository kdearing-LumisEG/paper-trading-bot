"""Read-only adapter for retrieving historical stock bars from Alpaca."""

from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import pandas as pd
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from trading_bot.config import Settings, load_settings
from trading_bot.data.coverage import audit_session_coverage
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

    start = end - timedelta(days=lookback_calendar_days)

    return start, end


def fetch_recent_bars(
    settings: Settings,
    lookback_calendar_days: int = 14,
) -> tuple[pd.DataFrame, datetime, datetime]:
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
        feed=_resolve_data_feed(settings.data_feed),
    )

    response = client.get_stock_bars(request)
    frame = response.df.reset_index()

    if frame.empty:
        raise ValueError(
            f"Alpaca returned no bars for {settings.symbol}."
        )

    return frame, start, end


def main() -> None:
    """Download, validate, audit, save, and reload market bars."""

    settings = load_settings()

    raw_bars, start, end = fetch_recent_bars(settings)

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

    audit = audit_session_coverage(
        frame=session_bars,
        timeframe_minutes=settings.timeframe_minutes,
        start=start,
        end=end,
    )

    coverage_columns = [
        "session_date",
        "expected_bars",
        "actual_bars",
        "missing_bars",
        "unexpected_bars",
        "complete",
    ]

    print()
    print("Session coverage report:")
    print(
        audit.sessions[coverage_columns].to_string(
            index=False
        )
    )

    if not audit.is_complete:
        print()
        print("Coverage audit failed.")

        if not audit.missing_timestamps.empty:
            print("First missing timestamps:")
            for timestamp in audit.missing_timestamps[:10]:
                print(f"  {timestamp}")

        if not audit.unexpected_timestamps.empty:
            print("First unexpected timestamps:")
            for timestamp in audit.unexpected_timestamps[:10]:
                print(f"  {timestamp}")

        raise ValueError(
            "Historical bars did not pass the "
            "exchange-session coverage audit."
        )

    output_directory = Path("data/processed")

    bars_path = output_directory / (
        f"{settings.symbol}_"
        f"{settings.timeframe_minutes}min.parquet"
    )

    coverage_path = output_directory / (
        f"{settings.symbol}_"
        f"{settings.timeframe_minutes}min_coverage.csv"
    )

    save_bars(session_bars, bars_path)

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    audit.sessions.to_csv(
        coverage_path,
        index=False,
    )

    reloaded_bars = validate_bars(
        load_bars(bars_path),
        expected_symbol=settings.symbol,
        timeframe_minutes=settings.timeframe_minutes,
    )

    print()
    print("Historical-data pipeline succeeded.")
    print(f"Symbol: {settings.symbol}")
    print(f"Feed: {settings.data_feed}")
    print(
        f"Timeframe: "
        f"{settings.timeframe_minutes} minutes"
    )
    print(f"Raw rows received: {len(raw_bars)}")
    print(
        f"Validated session rows: "
        f"{len(reloaded_bars)}"
    )
    print(
        f"Complete trading sessions: "
        f"{len(audit.sessions)}"
    )
    print(f"Bars file: {bars_path.resolve()}")
    print(
        f"Coverage report: "
        f"{coverage_path.resolve()}"
    )
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