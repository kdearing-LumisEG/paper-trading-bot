"""Broker-neutral models used by paper-trading execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import math
import re


_CLIENT_ORDER_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")


class BrokerModelError(ValueError):
    """Raised when a broker-neutral model is invalid."""


class OrderSide(str, Enum):
    """Supported long-only order sides."""

    BUY = "buy"
    SELL = "sell"


class BrokerOrderStatus(str, Enum):
    """Normalized broker order states."""

    NEW = "new"
    ACCEPTED = "accepted"
    PENDING_NEW = "pending_new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    DONE_FOR_DAY = "done_for_day"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REPLACED = "replaced"
    PENDING_CANCEL = "pending_cancel"
    PENDING_REPLACE = "pending_replace"
    REJECTED = "rejected"
    STOPPED = "stopped"
    SUSPENDED = "suspended"
    CALCULATED = "calculated"
    HELD = "held"
    UNKNOWN = "unknown"

    @property
    def is_terminal(self) -> bool:
        """Return whether no more fills are expected."""

        return self in {
            BrokerOrderStatus.FILLED,
            BrokerOrderStatus.DONE_FOR_DAY,
            BrokerOrderStatus.CANCELED,
            BrokerOrderStatus.EXPIRED,
            BrokerOrderStatus.REPLACED,
            BrokerOrderStatus.REJECTED,
            BrokerOrderStatus.STOPPED,
            BrokerOrderStatus.SUSPENDED,
            BrokerOrderStatus.CALCULATED,
        }


@dataclass(frozen=True)
class MarketOrderRequest:
    """Broker-neutral request for a whole-share market order."""

    symbol: str
    quantity: int
    side: OrderSide
    client_order_id: str

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        client_order_id = self.client_order_id.strip()

        if not symbol:
            raise BrokerModelError(
                "symbol cannot be empty."
            )

        if (
            isinstance(self.quantity, bool)
            or not isinstance(self.quantity, int)
            or self.quantity <= 0
        ):
            raise BrokerModelError(
                "quantity must be a positive integer."
            )

        if not isinstance(self.side, OrderSide):
            raise BrokerModelError(
                "side must be an OrderSide value."
            )

        if not client_order_id:
            raise BrokerModelError(
                "client_order_id cannot be empty."
            )

        if len(client_order_id) > 48:
            raise BrokerModelError(
                "client_order_id cannot exceed 48 characters."
            )

        if not _CLIENT_ORDER_ID_PATTERN.fullmatch(
            client_order_id
        ):
            raise BrokerModelError(
                "client_order_id contains unsupported characters."
            )

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(
            self,
            "client_order_id",
            client_order_id,
        )


@dataclass(frozen=True)
class BrokerOrder:
    """Normalized broker order returned by an adapter."""

    order_id: str
    client_order_id: str
    symbol: str
    quantity: float
    side: OrderSide
    status: BrokerOrderStatus
    filled_quantity: float = 0.0
    filled_average_price: float | None = None
    submitted_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.order_id.strip():
            raise BrokerModelError(
                "order_id cannot be empty."
            )

        if not self.client_order_id.strip():
            raise BrokerModelError(
                "client_order_id cannot be empty."
            )

        if not self.symbol.strip():
            raise BrokerModelError(
                "symbol cannot be empty."
            )

        for field_name, value in {
            "quantity": self.quantity,
            "filled_quantity": self.filled_quantity,
        }.items():
            if not math.isfinite(value) or value < 0:
                raise BrokerModelError(
                    f"{field_name} must be finite and nonnegative."
                )

        if (
            self.filled_average_price is not None
            and (
                not math.isfinite(
                    self.filled_average_price
                )
                or self.filled_average_price <= 0
            )
        ):
            raise BrokerModelError(
                "filled_average_price must be finite and positive."
            )


@dataclass(frozen=True)
class AccountSnapshot:
    """Normalized paper-account balances and trading state."""

    account_id: str
    cash: float
    buying_power: float
    equity: float
    trading_blocked: bool
    account_blocked: bool


@dataclass(frozen=True)
class PositionSnapshot:
    """Normalized open position returned by a broker."""

    symbol: str
    quantity: float
    average_entry_price: float
    market_value: float
    unrealized_pnl: float
