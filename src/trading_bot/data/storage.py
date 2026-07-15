"""Local storage for validated historical market bars."""

from pathlib import Path

import pandas as pd


def save_bars(
    frame: pd.DataFrame,
    path: Path,
) -> Path:
    """Save a dataframe as a Parquet file."""

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    frame.to_parquet(
        path,
        index=False,
    )

    return path


def load_bars(path: Path) -> pd.DataFrame:
    """Load bars from a Parquet file."""

    if not path.exists():
        raise FileNotFoundError(
            f"Market-data file not found: {path}"
        )

    return pd.read_parquet(path)
