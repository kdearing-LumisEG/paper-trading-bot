"""Persistent local state for the strategy-owned paper position."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import math
from pathlib import Path
from typing import Protocol


class PositionStateError(ValueError):
    """Raised when persisted position state is invalid."""


class PositionPhase(str, Enum):
    """Durable lifecycle phase for one owned position generation."""

    FLAT = "flat"
    ENTRY_PENDING = "entry_pending"
    OPEN = "open"
    EXIT_PENDING = "exit_pending"
    RECONCILIATION_REQUIRED = (
        "reconciliation_required"
    )


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
    schema_version: int = 2
    strategy_name: str | None = None
    position_generation_id: str | None = None
    phase: PositionPhase | None = None
    entry_intent_id: str | None = None
    entry_client_order_id: str | None = None
    entry_broker_order_id: str | None = None
    entry_filled_at: datetime | None = None
    exit_intent_id: str | None = None
    exit_client_order_id: str | None = None
    exit_broker_order_id: str | None = None
    exit_filled_at: datetime | None = None
    last_reconciled_at: datetime | None = None
    legacy_open: bool = False

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

        if self.schema_version not in {1, 2}:
            raise PositionStateError(
                "Unsupported tracked-position schema version."
            )

        phase = self.phase
        if phase is None:
            phase = (
                PositionPhase.OPEN
                if self.quantity > 0
                else PositionPhase.FLAT
            )

        if not isinstance(phase, PositionPhase):
            raise PositionStateError(
                "phase must be a PositionPhase value."
            )

        if (
            phase is PositionPhase.FLAT
            and self.quantity != 0
        ):
            raise PositionStateError(
                "A flat tracked position must have zero quantity."
            )

        if (
            phase in {
                PositionPhase.OPEN,
                PositionPhase.EXIT_PENDING,
            }
            and self.quantity <= 0
        ):
            raise PositionStateError(
                "An open tracked position must have positive quantity."
            )

        object.__setattr__(self, "phase", phase)

        for field_name in (
            "entry_filled_at",
            "exit_filled_at",
            "last_reconciled_at",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self,
                    field_name,
                    _utc_datetime(value),
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
        schema_version: int = 2,
        strategy_name: str | None = None,
        position_generation_id: str | None = None,
        entry_intent_id: str | None = None,
        entry_client_order_id: str | None = None,
        entry_broker_order_id: str | None = None,
        entry_filled_at: datetime | None = None,
        exit_intent_id: str | None = None,
        exit_client_order_id: str | None = None,
        exit_broker_order_id: str | None = None,
        exit_filled_at: datetime | None = None,
        last_reconciled_at: datetime | None = None,
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
            schema_version=schema_version,
            strategy_name=strategy_name,
            position_generation_id=(
                position_generation_id
            ),
            phase=PositionPhase.FLAT,
            entry_intent_id=entry_intent_id,
            entry_client_order_id=(
                entry_client_order_id
            ),
            entry_broker_order_id=(
                entry_broker_order_id
            ),
            entry_filled_at=entry_filled_at,
            exit_intent_id=exit_intent_id,
            exit_client_order_id=(
                exit_client_order_id
            ),
            exit_broker_order_id=(
                exit_broker_order_id
            ),
            exit_filled_at=exit_filled_at,
            last_reconciled_at=(
                last_reconciled_at
            ),
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
                "version": 2,
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

        if payload.get("version") not in {1, 2}:
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
            state_version = int(
                payload.get("version", 1)
            )
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

            quantity = float(raw_position["quantity"])
            phase = (
                PositionPhase(
                    str(raw_position["phase"])
                )
                if state_version == 2
                else (
                    PositionPhase
                    .RECONCILIATION_REQUIRED
                    if quantity > 0
                    else PositionPhase.FLAT
                )
            )

            def optional_text(
                field_name: str,
            ) -> str | None:
                value = raw_position.get(field_name)
                return (
                    str(value)
                    if value is not None
                    else None
                )

            def optional_time(
                field_name: str,
            ) -> datetime | None:
                value = raw_position.get(field_name)
                return (
                    datetime.fromisoformat(str(value))
                    if value is not None
                    else None
                )

            return TrackedPosition(
                symbol=normalized_symbol,
                quantity=quantity,
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
                schema_version=state_version,
                strategy_name=optional_text(
                    "strategy_name"
                ),
                position_generation_id=optional_text(
                    "position_generation_id"
                ),
                phase=phase,
                entry_intent_id=optional_text(
                    "entry_intent_id"
                ),
                entry_client_order_id=optional_text(
                    "entry_client_order_id"
                ),
                entry_broker_order_id=optional_text(
                    "entry_broker_order_id"
                ),
                entry_filled_at=optional_time(
                    "entry_filled_at"
                ),
                exit_intent_id=optional_text(
                    "exit_intent_id"
                ),
                exit_client_order_id=optional_text(
                    "exit_client_order_id"
                ),
                exit_broker_order_id=optional_text(
                    "exit_broker_order_id"
                ),
                exit_filled_at=optional_time(
                    "exit_filled_at"
                ),
                last_reconciled_at=optional_time(
                    "last_reconciled_at"
                ),
                legacy_open=(
                    state_version == 1
                    and quantity > 0
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
        if position.legacy_open:
            raise PositionStateError(
                "A legacy open position cannot be upgraded automatically."
            )

        payload = self._load_payload()
        payload["version"] = 2
        positions = payload["positions"]

        assert isinstance(positions, dict)

        record = asdict(position)
        record["schema_version"] = 2
        record["phase"] = position.phase.value
        record["updated_at"] = (
            position.updated_at.isoformat()
        )
        record.pop("legacy_open", None)

        for field_name in (
            "entry_filled_at",
            "exit_filled_at",
            "last_reconciled_at",
        ):
            value = getattr(position, field_name)
            record[field_name] = (
                value.isoformat()
                if value is not None
                else None
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
