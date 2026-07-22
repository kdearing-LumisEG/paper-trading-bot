"""Models for converting strategy signals into paper orders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import math
import re

from trading_bot.backtest.risk_manager import (
    SessionRiskSnapshot,
)
from trading_bot.broker.models import (
    MarketOrderRequest,
)
from trading_bot.execution.models import (
    ExecutionResult,
)


_STRATEGY_NAME_PATTERN = re.compile(
    r"^[A-Za-z0-9._:-]+$"
)


class SignalModelError(ValueError):
    """Raised when a signal-execution model is invalid."""


class StrategySignal(str, Enum):
    """Supported deterministic strategy signals."""

    HOLD = "hold"
    ENTER_LONG = "enter_long"
    EXIT_LONG = "exit_long"


class SignalHandlingOutcome(str, Enum):
    """High-level result of handling one strategy signal."""

    NO_ACTION = "no_action"
    BLOCKED = "blocked"
    ORDER_ATTEMPTED = "order_attempted"


@dataclass(frozen=True)
class StrategySignalEvent:
    """One timestamped strategy decision ready for execution."""

    strategy_name: str
    symbol: str
    signal: StrategySignal
    signal_time: datetime
    entry_quantity: int = 1
    timeframe_minutes: int = 1
    reference_price: float | None = None
    action: str | None = None
    identity_time: datetime | None = None

    def __post_init__(self) -> None:
        strategy_name = (
            self.strategy_name.strip()
        )
        symbol = self.symbol.strip().upper()

        if not strategy_name:
            raise SignalModelError(
                "strategy_name cannot be empty."
            )

        if not _STRATEGY_NAME_PATTERN.fullmatch(
            strategy_name
        ):
            raise SignalModelError(
                "strategy_name contains unsupported characters."
            )

        if not symbol:
            raise SignalModelError(
                "symbol cannot be empty."
            )

        if not isinstance(
            self.signal,
            StrategySignal,
        ):
            raise SignalModelError(
                "signal must be a StrategySignal value."
            )

        if (
            isinstance(
                self.entry_quantity,
                bool,
            )
            or not isinstance(
                self.entry_quantity,
                int,
            )
            or self.entry_quantity <= 0
        ):
            raise SignalModelError(
                "entry_quantity must be a positive integer."
            )

        if (
            isinstance(self.timeframe_minutes, bool)
            or not isinstance(self.timeframe_minutes, int)
            or self.timeframe_minutes <= 0
        ):
            raise SignalModelError(
                "timeframe_minutes must be a positive integer."
            )

        if (
            self.reference_price is not None
            and (
                not math.isfinite(self.reference_price)
                or self.reference_price <= 0
            )
        ):
            raise SignalModelError(
                "reference_price must be positive when present."
            )

        if self.action is not None:
            action = self.action.strip()
            if not action or not _STRATEGY_NAME_PATTERN.fullmatch(
                action
            ):
                raise SignalModelError(
                    "action contains unsupported characters."
                )
            object.__setattr__(self, "action", action)

        signal_time = self.signal_time

        if signal_time.tzinfo is None:
            signal_time = signal_time.replace(
                tzinfo=timezone.utc
            )
        else:
            signal_time = signal_time.astimezone(
                timezone.utc
            )

        object.__setattr__(
            self,
            "strategy_name",
            strategy_name,
        )
        object.__setattr__(
            self,
            "symbol",
            symbol,
        )
        object.__setattr__(
            self,
            "signal_time",
            signal_time,
        )

        identity_time = self.identity_time
        if identity_time is not None:
            if identity_time.tzinfo is None:
                identity_time = identity_time.replace(
                    tzinfo=timezone.utc
                )
            else:
                identity_time = identity_time.astimezone(
                    timezone.utc
                )
            object.__setattr__(
                self,
                "identity_time",
                identity_time,
            )

    @property
    def action_name(self) -> str:
        """Return the durable action identity component."""

        return self.action or self.signal.value

    @property
    def action_identity_time(self) -> datetime:
        """Return the stable timestamp used for durable identity."""

        return self.identity_time or self.signal_time


@dataclass(frozen=True)
class SignalHandlingResult:
    """Auditable result of one signal-to-order decision."""

    event: StrategySignalEvent
    outcome: SignalHandlingOutcome
    reason: str
    position_quantity_before: float
    risk_snapshot: SessionRiskSnapshot
    request: MarketOrderRequest | None = None
    execution_result: ExecutionResult | None = None
    realized_net_pnl_recorded: float | None = None
