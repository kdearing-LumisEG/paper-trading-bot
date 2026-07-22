"""Durable strategy order-intent lifecycle state."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import math
from pathlib import Path
from typing import Protocol

from trading_bot.broker.models import OrderSide


ORDER_STATE_VERSION = 1


class OrderStateError(ValueError):
    """Raised when durable order state is invalid or corrupt."""


class OrderLifecycleState(str, Enum):
    """Durable states for one strategy-generated broker order."""

    CREATED = "created"
    SUBMITTING = "submitting"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    RECONCILIATION_REQUIRED = (
        "reconciliation_required"
    )

    @property
    def is_terminal(self) -> bool:
        """Return whether the broker lifecycle is conclusively terminal."""

        return self in {
            OrderLifecycleState.FILLED,
            OrderLifecycleState.CANCELED,
            OrderLifecycleState.REJECTED,
            OrderLifecycleState.EXPIRED,
        }

    @property
    def is_unresolved(self) -> bool:
        """Return whether reconciliation or broker progress remains."""

        return not self.is_terminal


def _utc_datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise OrderStateError(
            "Order-state timestamps must be datetimes."
        )

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def _optional_utc_datetime(
    value: datetime | None,
) -> datetime | None:
    if value is None:
        return None
    return _utc_datetime(value)


@dataclass(frozen=True)
class OrderIntent:
    """Immutable durable state for one logical strategy action."""

    intent_id: str
    strategy_name: str
    symbol: str
    timeframe_minutes: int
    signal_bar_end: datetime
    action: str
    side: OrderSide
    requested_quantity: int
    client_order_id: str
    position_generation_id: str
    lifecycle_state: OrderLifecycleState
    created_at: datetime
    updated_at: datetime
    schema_version: int = ORDER_STATE_VERSION
    broker_order_id: str | None = None
    broker_status: str | None = None
    filled_quantity: float = 0.0
    average_fill_price: float | None = None
    submitted_at: datetime | None = None
    last_reconciled_at: datetime | None = None
    cancellation_requested_at: datetime | None = None
    terminal_at: datetime | None = None
    rejection_reason: str | None = None
    last_error_type: str | None = None
    last_error_message: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "intent_id",
            "strategy_name",
            "symbol",
            "action",
            "client_order_id",
            "position_generation_id",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise OrderStateError(
                    f"{field_name} cannot be empty."
                )
            object.__setattr__(self, field_name, value)

        object.__setattr__(
            self,
            "symbol",
            self.symbol.upper(),
        )

        if self.schema_version != ORDER_STATE_VERSION:
            raise OrderStateError(
                "Unsupported order-intent schema version."
            )

        if (
            isinstance(self.timeframe_minutes, bool)
            or not isinstance(self.timeframe_minutes, int)
            or self.timeframe_minutes <= 0
        ):
            raise OrderStateError(
                "timeframe_minutes must be a positive integer."
            )

        if (
            isinstance(self.requested_quantity, bool)
            or not isinstance(self.requested_quantity, int)
            or self.requested_quantity <= 0
        ):
            raise OrderStateError(
                "requested_quantity must be a positive integer."
            )

        if not isinstance(self.side, OrderSide):
            raise OrderStateError(
                "side must be an OrderSide value."
            )

        if not isinstance(
            self.lifecycle_state,
            OrderLifecycleState,
        ):
            raise OrderStateError(
                "lifecycle_state is invalid."
            )

        if (
            not math.isfinite(self.filled_quantity)
            or self.filled_quantity < 0
            or self.filled_quantity
            > self.requested_quantity
        ):
            raise OrderStateError(
                "filled_quantity must be finite and within the request."
            )

        if (
            self.average_fill_price is not None
            and (
                not math.isfinite(self.average_fill_price)
                or self.average_fill_price <= 0
            )
        ):
            raise OrderStateError(
                "average_fill_price must be positive when present."
            )

        if (
            self.filled_quantity > 0
            and self.average_fill_price is None
        ):
            raise OrderStateError(
                "Confirmed fills require an average fill price."
            )

        if (
            self.lifecycle_state is OrderLifecycleState.FILLED
            and self.filled_quantity != self.requested_quantity
        ):
            raise OrderStateError(
                "A filled intent must contain the full requested quantity."
            )

        if (
            self.lifecycle_state
            is OrderLifecycleState.PARTIALLY_FILLED
            and not (
                0
                < self.filled_quantity
                < self.requested_quantity
            )
        ):
            raise OrderStateError(
                "A partially filled intent requires an incomplete fill."
            )

        if (
            self.lifecycle_state
            in {
                OrderLifecycleState.CREATED,
                OrderLifecycleState.SUBMITTING,
                OrderLifecycleState.SUBMITTED,
                OrderLifecycleState.ACCEPTED,
            }
            and self.filled_quantity != 0
        ):
            raise OrderStateError(
                "A pending zero-fill lifecycle cannot contain fills."
            )

        for field_name in (
            "signal_bar_end",
            "created_at",
            "updated_at",
        ):
            object.__setattr__(
                self,
                field_name,
                _utc_datetime(getattr(self, field_name)),
            )

        for field_name in (
            "submitted_at",
            "last_reconciled_at",
            "cancellation_requested_at",
            "terminal_at",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_utc_datetime(
                    getattr(self, field_name)
                ),
            )

        if self.updated_at < self.created_at:
            raise OrderStateError(
                "updated_at cannot precede created_at."
            )


class OrderStateStore(Protocol):
    """Persistence contract for durable order intents."""

    def load_all(self) -> tuple[OrderIntent, ...]: ...

    def get_by_intent_id(
        self,
        intent_id: str,
    ) -> OrderIntent | None: ...

    def get_by_client_order_id(
        self,
        client_order_id: str,
    ) -> OrderIntent | None: ...

    def save(self, intent: OrderIntent) -> None: ...

    def list_unresolved(self) -> tuple[OrderIntent, ...]: ...


class NullOrderStateStore:
    """Unavailable durable state used by safe compatibility wiring."""

    durable = False

    def load_all(self) -> tuple[OrderIntent, ...]:
        return ()

    def get_by_intent_id(
        self,
        intent_id: str,
    ) -> OrderIntent | None:
        del intent_id
        return None

    def get_by_client_order_id(
        self,
        client_order_id: str,
    ) -> OrderIntent | None:
        del client_order_id
        return None

    def save(self, intent: OrderIntent) -> None:
        del intent
        raise OrderStateError(
            "Durable order-state storage is not configured."
        )

    def list_unresolved(self) -> tuple[OrderIntent, ...]:
        return ()


class JsonOrderStateStore:
    """Atomically persist a versioned collection of order intents."""

    durable = True

    def __init__(self, path: Path) -> None:
        self._path = path

    @staticmethod
    def _to_record(intent: OrderIntent) -> dict[str, object]:
        record = asdict(intent)
        record["side"] = intent.side.value
        record["lifecycle_state"] = (
            intent.lifecycle_state.value
        )

        for field_name in (
            "signal_bar_end",
            "created_at",
            "updated_at",
            "submitted_at",
            "last_reconciled_at",
            "cancellation_requested_at",
            "terminal_at",
        ):
            value = getattr(intent, field_name)
            record[field_name] = (
                value.isoformat()
                if value is not None
                else None
            )

        return record

    @staticmethod
    def _required_integer(
        record: dict[str, object],
        field_name: str,
    ) -> int:
        value = record.get(field_name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise OrderStateError(
                f"Order intent has invalid {field_name}."
            )
        return value

    @staticmethod
    def _parse_timestamp(
        record: dict[str, object],
        field_name: str,
        *,
        required: bool,
    ) -> datetime | None:
        value = record.get(field_name)
        if value is None:
            if required:
                raise OrderStateError(
                    f"Order intent is missing {field_name}."
                )
            return None

        try:
            return datetime.fromisoformat(str(value))
        except ValueError as exc:
            raise OrderStateError(
                f"Order intent has invalid {field_name}."
            ) from exc

    @classmethod
    def _from_record(
        cls,
        record: object,
    ) -> OrderIntent:
        if not isinstance(record, dict):
            raise OrderStateError(
                "Order-state records must be mappings."
            )

        try:
            return OrderIntent(
                schema_version=cls._required_integer(
                    record,
                    "schema_version",
                ),
                intent_id=str(record["intent_id"]),
                strategy_name=str(record["strategy_name"]),
                symbol=str(record["symbol"]),
                timeframe_minutes=cls._required_integer(
                    record,
                    "timeframe_minutes",
                ),
                signal_bar_end=cls._parse_timestamp(
                    record,
                    "signal_bar_end",
                    required=True,
                ),
                action=str(record["action"]),
                side=OrderSide(str(record["side"])),
                requested_quantity=cls._required_integer(
                    record,
                    "requested_quantity",
                ),
                client_order_id=str(
                    record["client_order_id"]
                ),
                position_generation_id=str(
                    record["position_generation_id"]
                ),
                lifecycle_state=OrderLifecycleState(
                    str(record["lifecycle_state"])
                ),
                broker_order_id=(
                    str(record["broker_order_id"])
                    if record.get("broker_order_id")
                    is not None
                    else None
                ),
                broker_status=(
                    str(record["broker_status"])
                    if record.get("broker_status")
                    is not None
                    else None
                ),
                filled_quantity=float(
                    record.get("filled_quantity", 0.0)
                ),
                average_fill_price=(
                    float(record["average_fill_price"])
                    if record.get("average_fill_price")
                    is not None
                    else None
                ),
                created_at=cls._parse_timestamp(
                    record,
                    "created_at",
                    required=True,
                ),
                updated_at=cls._parse_timestamp(
                    record,
                    "updated_at",
                    required=True,
                ),
                submitted_at=cls._parse_timestamp(
                    record,
                    "submitted_at",
                    required=False,
                ),
                last_reconciled_at=cls._parse_timestamp(
                    record,
                    "last_reconciled_at",
                    required=False,
                ),
                cancellation_requested_at=(
                    cls._parse_timestamp(
                        record,
                        "cancellation_requested_at",
                        required=False,
                    )
                ),
                terminal_at=cls._parse_timestamp(
                    record,
                    "terminal_at",
                    required=False,
                ),
                rejection_reason=(
                    str(record["rejection_reason"])
                    if record.get("rejection_reason")
                    is not None
                    else None
                ),
                last_error_type=(
                    str(record["last_error_type"])
                    if record.get("last_error_type")
                    is not None
                    else None
                ),
                last_error_message=(
                    str(record["last_error_message"])
                    if record.get("last_error_message")
                    is not None
                    else None
                ),
            )
        except (
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            if isinstance(exc, OrderStateError):
                raise
            raise OrderStateError(
                "Order-state record is invalid."
            ) from exc

    def _load(self) -> list[OrderIntent]:
        if not self._path.exists():
            return []

        try:
            payload = json.loads(
                self._path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise OrderStateError(
                "Order-state file could not be read."
            ) from exc

        if not isinstance(payload, dict):
            raise OrderStateError(
                "Order-state file must contain a JSON object."
            )

        if payload.get("version") != ORDER_STATE_VERSION:
            raise OrderStateError(
                "Unsupported order-state version."
            )

        records = payload.get("intents")
        if not isinstance(records, list):
            raise OrderStateError(
                "Order-state intents must be a list."
            )

        intents = [
            self._from_record(record)
            for record in records
        ]

        intent_ids: set[str] = set()
        client_ids: set[str] = set()
        for intent in intents:
            if intent.intent_id in intent_ids:
                raise OrderStateError(
                    "Duplicate intent_id in order state."
                )
            if intent.client_order_id in client_ids:
                raise OrderStateError(
                    "Duplicate client_order_id in order state."
                )
            intent_ids.add(intent.intent_id)
            client_ids.add(intent.client_order_id)

        return sorted(
            intents,
            key=lambda intent: intent.intent_id,
        )

    def load_all(self) -> tuple[OrderIntent, ...]:
        return tuple(self._load())

    def get_by_intent_id(
        self,
        intent_id: str,
    ) -> OrderIntent | None:
        return next(
            (
                intent
                for intent in self._load()
                if intent.intent_id == intent_id
            ),
            None,
        )

    def get_by_client_order_id(
        self,
        client_order_id: str,
    ) -> OrderIntent | None:
        return next(
            (
                intent
                for intent in self._load()
                if intent.client_order_id
                == client_order_id
            ),
            None,
        )

    def save(self, intent: OrderIntent) -> None:
        intents = self._load()
        existing_by_id = {
            item.intent_id: item
            for item in intents
        }
        existing = existing_by_id.get(intent.intent_id)

        if (
            existing is not None
            and existing.client_order_id
            != intent.client_order_id
        ):
            raise OrderStateError(
                "An intent_id cannot change client_order_id."
            )

        if existing is not None:
            immutable_fields = (
                "strategy_name",
                "symbol",
                "timeframe_minutes",
                "signal_bar_end",
                "action",
                "side",
                "requested_quantity",
                "client_order_id",
                "position_generation_id",
                "created_at",
            )
            if any(
                getattr(existing, field_name)
                != getattr(intent, field_name)
                for field_name in immutable_fields
            ):
                raise OrderStateError(
                    "Durable order-intent identity fields cannot change."
                )

        for item in intents:
            if (
                item.intent_id != intent.intent_id
                and item.client_order_id
                == intent.client_order_id
            ):
                raise OrderStateError(
                    "client_order_id already belongs to another intent."
                )

        existing_by_id[intent.intent_id] = intent
        ordered = sorted(
            existing_by_id.values(),
            key=lambda item: item.intent_id,
        )

        payload = {
            "version": ORDER_STATE_VERSION,
            "intents": [
                self._to_record(item)
                for item in ordered
            ],
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
        temporary_path.replace(self._path)

    def list_unresolved(self) -> tuple[OrderIntent, ...]:
        return tuple(
            intent
            for intent in self._load()
            if intent.lifecycle_state.is_unresolved
        )
