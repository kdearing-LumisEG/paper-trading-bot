"""Structured JSON-lines logging for execution attempts."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from enum import Enum
import json
from pathlib import Path
from typing import Protocol

from trading_bot.execution.models import ExecutionResult


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
