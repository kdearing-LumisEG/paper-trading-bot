"""Safe storage and metadata generation for historical datasets."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re

import pandas as pd

from trading_bot.data.range_audit import AuditedRange
from trading_bot.data.storage import save_bars


class RangeOutputError(ValueError):
    """Raised when a historical dataset cannot be saved safely."""


@dataclass(frozen=True)
class DatasetPaths:
    """Deterministic output paths for one historical dataset."""

    bars: Path
    coverage: Path
    metadata: Path

    def as_list(self) -> list[Path]:
        """Return all output paths."""

        return [
            self.bars,
            self.coverage,
            self.metadata,
        ]


def _normalize_symbol(symbol: str) -> str:
    """Return a safe uppercase symbol for use in filenames."""

    normalized = symbol.strip().upper()

    if not normalized:
        raise RangeOutputError(
            "symbol cannot be empty."
        )

    if re.fullmatch(
        r"[A-Z0-9.-]+",
        normalized,
    ) is None:
        raise RangeOutputError(
            "symbol contains unsupported filename characters."
        )

    return normalized


def build_dataset_paths(
    output_directory: Path,
    symbol: str,
    timeframe_minutes: int,
    start_date: date,
    end_date: date,
) -> DatasetPaths:
    """Build deterministic paths for one requested dataset."""

    if timeframe_minutes <= 0:
        raise RangeOutputError(
            "timeframe_minutes must be positive."
        )

    if start_date > end_date:
        raise RangeOutputError(
        "start cannot occur after end."
    )

    normalized_symbol = _normalize_symbol(
        symbol
    )

    base_name = (
        f"{normalized_symbol}_"
        f"{timeframe_minutes}min_"
        f"{start_date.isoformat()}_"
        f"{end_date.isoformat()}"
    )

    return DatasetPaths(
        bars=output_directory / (
            f"{base_name}.parquet"
        ),
        coverage=output_directory / (
            f"{base_name}_coverage.csv"
        ),
        metadata=output_directory / (
            f"{base_name}_metadata.json"
        ),
    )


def build_dataset_metadata(
    audited_range: AuditedRange,
    symbol: str,
    timeframe_minutes: int,
    data_feed: str,
    duplicate_rows_removed: int,
    generated_at_utc: datetime | None = None,
    price_adjustment: str = "raw",
) -> dict[str, object]:
    """Create JSON-compatible metadata for an audited dataset."""

    if audited_range.frame.empty:
        raise RangeOutputError(
            "Audited range cannot be empty."
        )

    if duplicate_rows_removed < 0:
        raise RangeOutputError(
            "duplicate_rows_removed cannot be negative."
        )

    generated_at = (
        generated_at_utc
        if generated_at_utc is not None
        else datetime.now(timezone.utc)
    )

    if generated_at.tzinfo is None:
        raise RangeOutputError(
            "generated_at_utc must be timezone-aware."
        )

    generated_at = generated_at.astimezone(
        timezone.utc
    )

    timestamps = pd.to_datetime(
        audited_range.frame["timestamp"],
        utc=True,
        errors="raise",
    )

    requested_end_inclusive = (
        audited_range.requested_end_exclusive.date()
        - timedelta(days=1)
    )

    return {
        "symbol": _normalize_symbol(symbol),
        "timeframe_minutes": timeframe_minutes,
        "data_feed": data_feed.strip().lower(),
        "requested_start": (
            audited_range.requested_start
            .date()
            .isoformat()
        ),
        "requested_end": (
            requested_end_inclusive.isoformat()
        ),
        "actual_first_timestamp": (
            timestamps.min().isoformat()
        ),
        "actual_last_timestamp": (
            timestamps.max().isoformat()
        ),
        "row_count": len(
            audited_range.frame
        ),
        "session_count": (
            audited_range.session_count
        ),
        "expected_bar_count": (
            audited_range.expected_bar_count
        ),
        "actual_bar_count": (
            audited_range.actual_bar_count
        ),
        "missing_bar_count": (
            audited_range.missing_bar_count
        ),
        "unexpected_bar_count": (
            audited_range.unexpected_bar_count
        ),
        "duplicate_rows_removed": (
            duplicate_rows_removed
        ),
        "generated_at_utc": (
            generated_at.isoformat()
        ),
        "price_adjustment": (
            price_adjustment.strip().lower()
        ),
        "regular_session_filter_applied": True,
    }


def save_audited_range(
    audited_range: AuditedRange,
    output_directory: Path,
    symbol: str,
    timeframe_minutes: int,
    data_feed: str,
    duplicate_rows_removed: int,
    overwrite: bool = False,
    generated_at_utc: datetime | None = None,
) -> DatasetPaths:
    """Save bars, coverage, and metadata without silent overwrites."""

    start_date = (
        audited_range.requested_start.date()
    )

    end_date = (
        audited_range.requested_end_exclusive.date()
        - timedelta(days=1)
    )

    paths = build_dataset_paths(
        output_directory=output_directory,
        symbol=symbol,
        timeframe_minutes=timeframe_minutes,
        start_date=start_date,
        end_date=end_date,
    )

    existing_paths = [
        path
        for path in paths.as_list()
        if path.exists()
    ]

    if existing_paths and not overwrite:
        existing_names = ", ".join(
            path.name
            for path in existing_paths
        )

        raise FileExistsError(
            "Refusing to overwrite existing dataset files: "
            f"{existing_names}"
        )

    metadata = build_dataset_metadata(
        audited_range=audited_range,
        symbol=symbol,
        timeframe_minutes=timeframe_minutes,
        data_feed=data_feed,
        duplicate_rows_removed=(
            duplicate_rows_removed
        ),
        generated_at_utc=generated_at_utc,
    )

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    save_bars(
        audited_range.frame,
        paths.bars,
    )

    audited_range.coverage.sessions.to_csv(
        paths.coverage,
        index=False,
    )

    with paths.metadata.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            metadata,
            file,
            ensure_ascii=False,
            indent=2,
        )

    return paths