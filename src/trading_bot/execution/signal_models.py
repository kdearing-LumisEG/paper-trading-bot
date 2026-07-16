"""Models for converting strategy signals into paper orders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
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
