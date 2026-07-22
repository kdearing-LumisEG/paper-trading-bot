"""Structured JSON-lines logging for execution attempts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import Enum
import json
from pathlib import Path
from typing import Protocol

from trading_bot.execution.models import ExecutionResult


@dataclass(frozen=True)
class OrderLifecycleEvent:
    """Correlated append-only event for order and position recovery."""

    event_type: str
    timestamp: datetime
    intent_id: str
    client_order_id: str
    position_generation_id: str
    strategy_name: str
    symbol: str
    action: str
    lifecycle_state: str
    event_version: int = 1
    broker_order_id: str | None = None
    filled_quantity: float = 0.0
    message: str | None = None


class OrderLifecycleLogger(Protocol):
    """Destination for correlated lifecycle events."""

    def log_event(
        self,
        event: OrderLifecycleEvent,
    ) -> None: ...


class NullOrderLifecycleLogger:
    """Discard lifecycle events."""

    def log_event(
        self,
        event: OrderLifecycleEvent,
    ) -> None:
        del event


class JsonlOrderLifecycleLogger:
    """Append versioned lifecycle events as JSON lines."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def log_event(
        self,
        event: OrderLifecycleEvent,
    ) -> None:
        self._path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        with self._path.open(
            "a",
            encoding="utf-8",
        ) as handle:
            json.dump(
                asdict(event),
                handle,
                default=JsonlExecutionLogger._json_default,
                sort_keys=True,
            )
            handle.write("\n")


class ExecutionLogger(Protocol):
    """Destination for completed execution results."""

    def log(self, result: ExecutionResult) -> None:
        """Persist one execution result."""


class NullExecutionLogger:
    """Discard execution logs."""

    def log(self, result: ExecutionResult) -> None:
        del result


class JsonlExecutionLogger:
    """Append one JSON document per execution attempt."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @staticmethod
    def _json_default(value: object) -> object:
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        raise TypeError(
            f"Object of type {type(value).__name__} "
            "is not JSON serializable."
        )

    def log(self, result: ExecutionResult) -> None:
        self._path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        payload = asdict(result)

        with self._path.open(
            "a",
            encoding="utf-8",
        ) as handle:
            json.dump(
                payload,
                handle,
                default=self._json_default,
                sort_keys=True,
            )
            handle.write("\n")
