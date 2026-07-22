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
    RECONCILIATION_REQUIRED = (
        "reconciliation_required"
    )


@dataclass(frozen=True)
class ExecutionSettings:
    """Polling and safety settings for paper execution."""

    dry_run: bool = True
    poll_interval_seconds: float = 1.0
    max_poll_attempts: int = 10
    cancel_on_timeout: bool = True
    cancellation_confirmation_poll_seconds: float = 1.0
    cancellation_confirmation_timeout_seconds: float = 10.0

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

        for field_name, value in {
            "cancellation_confirmation_poll_seconds": (
                self.cancellation_confirmation_poll_seconds
            ),
            "cancellation_confirmation_timeout_seconds": (
                self.cancellation_confirmation_timeout_seconds
            ),
        }.items():
            if not math.isfinite(value) or value <= 0:
                raise ExecutionSettingsError(
                    f"{field_name} must be finite and positive."
                )

        if (
            self.cancellation_confirmation_timeout_seconds
            < self.cancellation_confirmation_poll_seconds
        ):
            raise ExecutionSettingsError(
                "Cancellation confirmation timeout must be at least "
                "the poll interval."
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
    intent_id: str | None = None
    lifecycle_state: str | None = None
    newly_filled_quantity: float = 0.0
    audit_logging_error: str | None = None
