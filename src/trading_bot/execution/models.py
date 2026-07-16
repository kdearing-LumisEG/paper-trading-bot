"""Models for safe paper-order execution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math

from trading_bot.broker.models import (
    BrokerOrder,
    MarketOrderRequest,
)


class ExecutionSettingsError(ValueError):
    """Raised when execution settings are invalid."""


class ExecutionOutcome(str, Enum):
    """Final result of one execution attempt."""

    BLOCKED = "blocked"
    DRY_RUN = "dry_run"
    DUPLICATE = "duplicate"
    FILLED = "filled"
    TERMINAL = "terminal"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class ExecutionSettings:
    """Polling and safety settings for paper execution."""

    dry_run: bool = True
    poll_interval_seconds: float = 1.0
    max_poll_attempts: int = 10
    cancel_on_timeout: bool = True

    def __post_init__(self) -> None:
        if (
            not math.isfinite(
                self.poll_interval_seconds
            )
            or self.poll_interval_seconds < 0
        ):
            raise ExecutionSettingsError(
                "poll_interval_seconds must be finite and nonnegative."
            )

        if (
            isinstance(self.max_poll_attempts, bool)
            or not isinstance(
                self.max_poll_attempts,
                int,
            )
            or self.max_poll_attempts <= 0
        ):
            raise ExecutionSettingsError(
                "max_poll_attempts must be a positive integer."
            )


@dataclass(frozen=True)
class ExecutionResult:
    """Completed execution attempt and its final broker state."""

    request: MarketOrderRequest
    outcome: ExecutionOutcome
    message: str
    order: BrokerOrder | None = None
    poll_count: int = 0
    cancellation_requested: bool = False
