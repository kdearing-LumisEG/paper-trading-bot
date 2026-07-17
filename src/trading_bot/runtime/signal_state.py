"""Persistent deduplication state for processed market bars."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Protocol


class SignalStateStore(Protocol):
    """Persistence contract for completed market-signal cycles."""

    def is_processed(
        self,
        *,
        strategy_name: str,
        symbol: str,
        timeframe_minutes: int,
        bar_end: datetime,
    ) -> bool:
        """Return whether this bar or a later bar was processed."""

    def mark_processed(
        self,
        *,
        strategy_name: str,
        symbol: str,
        timeframe_minutes: int,
        bar_end: datetime,
        signal: str,
        handled_at: datetime,
    ) -> None:
        """Persist the most recent processed bar."""


class NullSignalStateStore:
    """Disable persistent signal deduplication."""

    def is_processed(
        self,
        *,
        strategy_name: str,
        symbol: str,
        timeframe_minutes: int,
        bar_end: datetime,
    ) -> bool:
        del (
            strategy_name,
            symbol,
            timeframe_minutes,
            bar_end,
        )
        return False

    def mark_processed(
        self,
        *,
        strategy_name: str,
        symbol: str,
        timeframe_minutes: int,
        bar_end: datetime,
        signal: str,
        handled_at: datetime,
    ) -> None:
        del (
            strategy_name,
            symbol,
            timeframe_minutes,
            bar_end,
            signal,
            handled_at,
        )


def _utc_datetime(
    value: datetime,
) -> datetime:
    if value.tzinfo is None:
        return value.replace(
            tzinfo=timezone.utc
        )

    return value.astimezone(
        timezone.utc
    )


def _state_key(
    strategy_name: str,
    symbol: str,
    timeframe_minutes: int,
) -> str:
    return (
        f"{strategy_name.strip()}|"
        f"{symbol.strip().upper()}|"
        f"{timeframe_minutes}"
    )


class JsonSignalStateStore:
    """Atomically persist the latest processed bar per strategy."""

    def __init__(
        self,
        path: Path,
    ) -> None:
        self._path = path

    def _load_payload(
        self,
    ) -> dict[str, object]:
        if not self._path.exists():
            return {
                "version": 1,
                "processed": {},
            }

        try:
            payload = json.loads(
                self._path.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ) as exc:
            raise ValueError(
                "Market-signal state file could not be read."
            ) from exc

        if not isinstance(payload, dict):
            raise ValueError(
                "Market-signal state must be a JSON object."
            )

        if payload.get("version") != 1:
            raise ValueError(
                "Unsupported market-signal state version."
            )

        processed = payload.get(
            "processed",
        )

        if not isinstance(
            processed,
            dict,
        ):
            raise ValueError(
                "Market-signal processed state must be a mapping."
            )

        return payload

    def is_processed(
        self,
        *,
        strategy_name: str,
        symbol: str,
        timeframe_minutes: int,
        bar_end: datetime,
    ) -> bool:
        payload = self._load_payload()

        processed = payload[
            "processed"
        ]

        assert isinstance(
            processed,
            dict,
        )

        record = processed.get(
            _state_key(
                strategy_name,
                symbol,
                timeframe_minutes,
            )
        )

        if record is None:
            return False

        if not isinstance(
            record,
            dict,
        ):
            raise ValueError(
                "Market-signal state record must be a mapping."
            )

        try:
            stored_bar_end = datetime.fromisoformat(
                str(record["bar_end"])
            )
        except (
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise ValueError(
                "Market-signal state record is invalid."
            ) from exc

        return _utc_datetime(
            bar_end
        ) <= _utc_datetime(
            stored_bar_end
        )

    def mark_processed(
        self,
        *,
        strategy_name: str,
        symbol: str,
        timeframe_minutes: int,
        bar_end: datetime,
        signal: str,
        handled_at: datetime,
    ) -> None:
        payload = self._load_payload()

        processed = payload[
            "processed"
        ]

        assert isinstance(
            processed,
            dict,
        )

        processed[
            _state_key(
                strategy_name,
                symbol,
                timeframe_minutes,
            )
        ] = {
            "bar_end": _utc_datetime(
                bar_end
            ).isoformat(),
            "signal": signal,
            "handled_at": _utc_datetime(
                handled_at
            ).isoformat(),
        }

        self._path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_path = self._path.with_suffix(
            self._path.suffix + ".tmp"
        )

        temporary_path.write_text(
            json.dumps(
                payload,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        temporary_path.replace(
            self._path
        )
