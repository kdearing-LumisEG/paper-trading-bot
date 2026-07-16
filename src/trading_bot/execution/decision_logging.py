"""Structured logging for signal-to-order decisions."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from enum import Enum
import json
from pathlib import Path
from typing import Protocol

from trading_bot.execution.signal_models import (
    SignalHandlingResult,
)


class SignalDecisionLogger(Protocol):
    """Destination for completed signal decisions."""

    def log(
        self,
        result: SignalHandlingResult,
    ) -> None:
        """Persist one signal decision."""


class NullSignalDecisionLogger:
    """Discard signal-decision logs."""

    def log(
        self,
        result: SignalHandlingResult,
    ) -> None:
        del result


class JsonlSignalDecisionLogger:
    """Append one JSON document per signal decision."""

    def __init__(
        self,
        path: Path,
    ) -> None:
        self._path = path

    @staticmethod
    def _json_default(
        value: object,
    ) -> object:
        if isinstance(value, Enum):
            return value.value

        if isinstance(
            value,
            (
                date,
                datetime,
            ),
        ):
            return value.isoformat()

        raise TypeError(
            f"Object of type "
            f"{type(value).__name__} "
            "is not JSON serializable."
        )

    def log(
        self,
        result: SignalHandlingResult,
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
                asdict(result),
                handle,
                default=self._json_default,
                sort_keys=True,
            )
            handle.write("\n")
