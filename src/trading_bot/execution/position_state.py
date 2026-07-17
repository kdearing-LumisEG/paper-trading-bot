"""Persistent local state for the strategy-owned paper position."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Protocol


class PositionStateError(ValueError):
    """Raised when persisted position state is invalid."""


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class TrackedPosition:
    """Local record of the position owned by this strategy."""

    symbol: str
    quantity: float
    average_entry_price: float | None
    updated_at: datetime
    source_order_id: str | None = None
    source_client_order_id: str | None = None
    adopted: bool = False

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()

        if not symbol:
            raise PositionStateError(
                "symbol cannot be empty."
            )

        if (
            not math.isfinite(self.quantity)
            or self.quantity < 0
        ):
            raise PositionStateError(
                "quantity must be finite and nonnegative."
            )

        if self.quantity == 0:
            average_entry_price = None
        else:
            average_entry_price = self.average_entry_price

            if (
                average_entry_price is None
                or not math.isfinite(average_entry_price)
                or average_entry_price <= 0
            ):
                raise PositionStateError(
                    "average_entry_price must be finite and "
                    "positive for an open position."
                )

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(
            self,
            "average_entry_price",
            average_entry_price,
        )
        object.__setattr__(
            self,
            "updated_at",
            _utc_datetime(self.updated_at),
        )

    @classmethod
    def flat(
        cls,
        *,
        symbol: str,
        updated_at: datetime,
        source_order_id: str | None = None,
        source_client_order_id: str | None = None,
        adopted: bool = False,
    ) -> "TrackedPosition":
        """Return a tracked flat-position state."""

        return cls(
            symbol=symbol,
            quantity=0.0,
            average_entry_price=None,
            updated_at=updated_at,
            source_order_id=source_order_id,
            source_client_order_id=source_client_order_id,
            adopted=adopted,
        )


class PositionStateStore(Protocol):
    """Persistence contract for strategy-owned position state."""

    def load(
        self,
        symbol: str,
    ) -> TrackedPosition | None:
        """Return tracked state for a symbol, when present."""

    def save(
        self,
        position: TrackedPosition,
    ) -> None:
        """Persist tracked state for a symbol."""


class NullPositionStateStore:
    """Disable persistent position tracking."""

    def load(
        self,
        symbol: str,
    ) -> TrackedPosition | None:
        del symbol
        return None

    def save(
        self,
        position: TrackedPosition,
    ) -> None:
        del position


class JsonPositionStateStore:
    """Atomically persist tracked positions to JSON."""

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
                "positions": {},
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
            raise PositionStateError(
                "Position-state file could not be read."
            ) from exc

        if not isinstance(payload, dict):
            raise PositionStateError(
                "Position-state file must contain a JSON object."
            )

        if payload.get("version") != 1:
            raise PositionStateError(
                "Unsupported position-state version."
            )

        positions = payload.get("positions")

        if not isinstance(positions, dict):
            raise PositionStateError(
                "Position-state positions must be a mapping."
            )

        return payload

    def load(
        self,
        symbol: str,
    ) -> TrackedPosition | None:
        normalized_symbol = symbol.strip().upper()
        payload = self._load_payload()
        positions = payload["positions"]

        assert isinstance(positions, dict)

        raw_position = positions.get(normalized_symbol)

        if raw_position is None:
            return None

        if not isinstance(raw_position, dict):
            raise PositionStateError(
                "Position-state record must be a mapping."
            )

        try:
            updated_at = datetime.fromisoformat(
                str(raw_position["updated_at"])
            )

            average_entry_price_value = raw_position.get(
                "average_entry_price"
            )

            average_entry_price = (
                None
                if average_entry_price_value is None
                else float(average_entry_price_value)
            )

            return TrackedPosition(
                symbol=normalized_symbol,
                quantity=float(raw_position["quantity"]),
                average_entry_price=average_entry_price,
                updated_at=updated_at,
                source_order_id=(
                    str(raw_position["source_order_id"])
                    if raw_position.get("source_order_id")
                    is not None
                    else None
                ),
                source_client_order_id=(
                    str(
                        raw_position[
                            "source_client_order_id"
                        ]
                    )
                    if raw_position.get(
                        "source_client_order_id"
                    )
                    is not None
                    else None
                ),
                adopted=bool(
                    raw_position.get("adopted", False)
                ),
            )
        except (
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise PositionStateError(
                "Position-state record is invalid."
            ) from exc

    def save(
        self,
        position: TrackedPosition,
    ) -> None:
        payload = self._load_payload()
        positions = payload["positions"]

        assert isinstance(positions, dict)

        record = asdict(position)
        record["updated_at"] = (
            position.updated_at.isoformat()
        )

        positions[position.symbol] = record

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

        temporary_path.replace(self._path)
