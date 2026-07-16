"""Merge and reconcile monthly historical-data chunks."""

from dataclasses import dataclass

import pandas as pd

from trading_bot.data.range_source import FetchedChunk
from trading_bot.data.validation import (
    NUMERIC_BAR_COLUMNS,
    REQUIRED_BAR_COLUMNS,
    validate_bars,
)


class RangeMergeError(ValueError):
    """Raised when monthly market-data chunks cannot be merged safely."""


@dataclass(frozen=True)
class MergedBars:
    """Validated result of merging monthly historical-data chunks."""

    frame: pd.DataFrame
    source_chunk_count: int
    nonempty_chunk_count: int
    duplicate_rows_removed: int


def _prepare_chunk_frame(
    frame: pd.DataFrame,
    chunk_number: int,
) -> pd.DataFrame:
    """Return a normalized copy of one nonempty chunk."""

    missing_columns = set(
        REQUIRED_BAR_COLUMNS
    ).difference(frame.columns)

    if missing_columns:
        missing = ", ".join(
            sorted(missing_columns)
        )
        raise RangeMergeError(
            f"Chunk {chunk_number} is missing "
            f"required columns: {missing}"
        )

    prepared = frame.loc[
        :,
        REQUIRED_BAR_COLUMNS,
    ].copy(deep=True)

    try:
        prepared["symbol"] = (
            prepared["symbol"]
            .astype(str)
            .str.strip()
            .str.upper()
        )

        prepared["timestamp"] = pd.to_datetime(
            prepared["timestamp"],
            utc=True,
            errors="raise",
        )

        for column in NUMERIC_BAR_COLUMNS:
            prepared[column] = pd.to_numeric(
                prepared[column],
                errors="raise",
            )
    except (TypeError, ValueError) as exc:
        raise RangeMergeError(
            f"Chunk {chunk_number} contains "
            "invalid timestamp or numeric values."
        ) from exc

    return prepared


def _reject_conflicting_duplicates(
    frame: pd.DataFrame,
) -> None:
    """Reject duplicate timestamps containing different bar values."""

    key_columns = [
        "symbol",
        "timestamp",
    ]

    value_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]

    duplicate_keys = frame.duplicated(
        subset=key_columns,
        keep=False,
    )

    if not duplicate_keys.any():
        return

    duplicate_rows = frame.loc[
        duplicate_keys,
        key_columns + value_columns,
    ]

    unique_value_counts = (
        duplicate_rows.groupby(
            key_columns,
            sort=False,
        )[value_columns]
        .nunique(dropna=False)
    )

    conflicting_groups = (
        unique_value_counts > 1
    ).any(axis=1)

    if conflicting_groups.any():
        first_conflict = (
            conflicting_groups[
                conflicting_groups
            ]
            .index[0]
        )

        symbol, timestamp = first_conflict

        raise RangeMergeError(
            "Conflicting duplicate bars found for "
            f"{symbol} at {timestamp}."
        )


def merge_fetched_chunks(
    fetched_chunks: list[FetchedChunk],
    expected_symbol: str,
    timeframe_minutes: int,
) -> MergedBars:
    """Merge monthly chunks into one sorted, validated dataframe."""

    if not fetched_chunks:
        raise RangeMergeError(
            "No fetched chunks were supplied."
        )

    prepared_frames: list[pd.DataFrame] = []

    for chunk_number, fetched_chunk in enumerate(
        fetched_chunks,
        start=1,
    ):
        if fetched_chunk.frame.empty:
            continue

        prepared_frames.append(
            _prepare_chunk_frame(
                frame=fetched_chunk.frame,
                chunk_number=chunk_number,
            )
        )

    if not prepared_frames:
        raise RangeMergeError(
            "All fetched chunks were empty."
        )

    merged = pd.concat(
        prepared_frames,
        ignore_index=True,
    )

    _reject_conflicting_duplicates(
        merged
    )

    duplicate_rows_removed = int(
        merged.duplicated(
            subset=REQUIRED_BAR_COLUMNS,
            keep="first",
        ).sum()
    )

    deduplicated = merged.drop_duplicates(
        subset=REQUIRED_BAR_COLUMNS,
        keep="first",
    ).reset_index(drop=True)

    validated = validate_bars(
        deduplicated,
        expected_symbol=expected_symbol,
        timeframe_minutes=timeframe_minutes,
    )

    return MergedBars(
        frame=validated,
        source_chunk_count=len(
            fetched_chunks
        ),
        nonempty_chunk_count=len(
            prepared_frames
        ),
        duplicate_rows_removed=(
            duplicate_rows_removed
        ),
    )