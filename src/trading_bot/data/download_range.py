"""Command-line pipeline for downloading explicit historical date ranges."""

from argparse import ArgumentParser, Namespace
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path

from trading_bot.config import Settings, load_settings
from trading_bot.data.date_ranges import (
    DateRangeChunk,
    parse_date_range,
)
from trading_bot.data.range_audit import (
    AuditedRange,
    audit_merged_range,
)
from trading_bot.data.range_merge import (
    MergedBars,
    merge_fetched_chunks,
)
from trading_bot.data.range_output import (
    DatasetPaths,
    save_audited_range,
)
from trading_bot.data.range_source import (
    ChunkFetcher,
    fetch_bars_by_month,
)


@dataclass(frozen=True)
class RangeDownloadResult:
    """Results from one completed historical range download."""

    merged: MergedBars
    audited: AuditedRange
    paths: DatasetPaths


def print_chunk_progress(
    current: int,
    total: int,
    chunk: DateRangeChunk,
) -> None:
    """Print safe progress without exposing credentials."""

    print(
        f"[{current}/{total}] "
        f"{chunk.start.date().isoformat()} through "
        f"{chunk.end.date().isoformat()} "
        "(exclusive end)"
    )


def run_range_download(
    settings: Settings,
    start_date: date,
    end_date: date,
    output_directory: Path = Path("data/processed"),
    overwrite: bool = False,
    fetch_chunk: ChunkFetcher | None = None,
    show_progress: bool = True,
    generated_at_utc: datetime | None = None,
) -> RangeDownloadResult:
    """Download, reconcile, audit, and save one historical dataset."""

    progress_callback = (
        print_chunk_progress
        if show_progress
        else None
    )

    fetched_chunks = fetch_bars_by_month(
        settings=settings,
        start_date=start_date,
        end_date=end_date,
        fetch_chunk=fetch_chunk,
        progress_callback=progress_callback,
    )

    merged = merge_fetched_chunks(
        fetched_chunks=fetched_chunks,
        expected_symbol=settings.symbol,
        timeframe_minutes=settings.timeframe_minutes,
    )

    audited = audit_merged_range(
        merged_bars=merged,
        expected_symbol=settings.symbol,
        timeframe_minutes=settings.timeframe_minutes,
        start_date=start_date,
        end_date=end_date,
    )

    paths = save_audited_range(
        audited_range=audited,
        output_directory=output_directory,
        symbol=settings.symbol,
        timeframe_minutes=settings.timeframe_minutes,
        data_feed=settings.data_feed,
        duplicate_rows_removed=(
            merged.duplicate_rows_removed
        ),
        overwrite=overwrite,
        generated_at_utc=generated_at_utc,
    )

    return RangeDownloadResult(
        merged=merged,
        audited=audited,
        paths=paths,
    )


def build_parser() -> ArgumentParser:
    """Build the command-line parser."""

    parser = ArgumentParser(
        description=(
            "Download and validate historical "
            "market bars for an explicit date range."
        )
    )

    parser.add_argument(
        "--start",
        required=True,
        help="Inclusive start date in YYYY-MM-DD format.",
    )

    parser.add_argument(
        "--end",
        required=True,
        help="Inclusive end date in YYYY-MM-DD format.",
    )

    parser.add_argument(
        "--symbol",
        default=None,
        help=(
            "Symbol override. Defaults to config/strategy.yaml."
        ),
    )

    parser.add_argument(
        "--timeframe-minutes",
        type=int,
        default=None,
        help=(
            "Bar interval override. "
            "Defaults to config/strategy.yaml."
        ),
    )

    parser.add_argument(
        "--output-directory",
        type=Path,
        default=Path("data/processed"),
        help="Directory for generated dataset files.",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacement of existing output files.",
    )

    return parser


def _settings_from_arguments(
    arguments: Namespace,
) -> Settings:
    """Load settings and apply non-secret CLI overrides."""

    settings = load_settings()

    symbol = (
        arguments.symbol.strip().upper()
        if arguments.symbol is not None
        else settings.symbol
    )

    timeframe_minutes = (
        arguments.timeframe_minutes
        if arguments.timeframe_minutes is not None
        else settings.timeframe_minutes
    )

    if not symbol:
        raise ValueError(
            "symbol cannot be empty."
        )

    if timeframe_minutes <= 0:
        raise ValueError(
            "timeframe-minutes must be positive."
        )

    return replace(
        settings,
        symbol=symbol,
        timeframe_minutes=timeframe_minutes,
    )


def _print_summary(
    result: RangeDownloadResult,
    settings: Settings,
    start_date: date,
    end_date: date,
) -> None:
    """Print a concise completed-download summary."""

    audited = result.audited

    print()
    print("Historical range download succeeded.")
    print(
        f"Requested range: "
        f"{start_date.isoformat()} through "
        f"{end_date.isoformat()} inclusive"
    )
    print(f"Symbol: {settings.symbol}")
    print(
        f"Timeframe: "
        f"{settings.timeframe_minutes} minutes"
    )
    print(f"Feed: {settings.data_feed}")
    print(
        f"Source chunks: "
        f"{result.merged.source_chunk_count}"
    )
    print(
        f"Nonempty chunks: "
        f"{result.merged.nonempty_chunk_count}"
    )
    print(
        f"Duplicate rows removed: "
        f"{result.merged.duplicate_rows_removed}"
    )
    print(
        f"Merged rows: "
        f"{audited.merged_row_count}"
    )
    print(
        f"Validated regular-session rows: "
        f"{audited.actual_bar_count}"
    )
    print(
        f"Exchange sessions: "
        f"{audited.session_count}"
    )
    print(
        f"Expected bars: "
        f"{audited.expected_bar_count}"
    )
    print(
        f"Missing bars: "
        f"{audited.missing_bar_count}"
    )
    print(
        f"Unexpected bars: "
        f"{audited.unexpected_bar_count}"
    )
    print(
        "Actual first timestamp: "
        f"{audited.frame['timestamp'].min()}"
    )
    print(
        "Actual last timestamp: "
        f"{audited.frame['timestamp'].max()}"
    )
    print(f"Bars file: {result.paths.bars.resolve()}")
    print(
        "Coverage file: "
        f"{result.paths.coverage.resolve()}"
    )
    print(
        "Metadata file: "
        f"{result.paths.metadata.resolve()}"
    )


def main(
    argv: Sequence[str] | None = None,
) -> int:
    """Run the command-line historical-download pipeline."""

    parser = build_parser()
    arguments = parser.parse_args(argv)

    start_date, end_date = parse_date_range(
        arguments.start,
        arguments.end,
    )

    settings = _settings_from_arguments(
        arguments
    )

    print(
        "Preparing historical download for "
        f"{settings.symbol}: "
        f"{start_date.isoformat()} through "
        f"{end_date.isoformat()} inclusive"
    )

    result = run_range_download(
        settings=settings,
        start_date=start_date,
        end_date=end_date,
        output_directory=arguments.output_directory,
        overwrite=arguments.overwrite,
    )

    _print_summary(
        result=result,
        settings=settings,
        start_date=start_date,
        end_date=end_date,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())