"""Persistent JSON storage for session risk state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from trading_bot.backtest.risk_manager import (
    RiskManager,
    SessionRiskConfig,
)


class RiskStateStore(Protocol):
    """Persistence contract for live paper-trading risk state."""

    def load(
        self,
        config: SessionRiskConfig,
    ) -> RiskManager:
        """Load a manager using the supplied active configuration."""

    def save(
        self,
        manager: RiskManager,
    ) -> None:
        """Persist current manager state."""


class NullRiskStateStore:
    """Keep risk state only in memory."""

    def load(
        self,
        config: SessionRiskConfig,
    ) -> RiskManager:
        return RiskManager(config)

    def save(
        self,
        manager: RiskManager,
    ) -> None:
        del manager


class JsonRiskStateStore:
    """Atomically persist session risk state to JSON."""

    def __init__(
        self,
        path: Path,
    ) -> None:
        self._path = path

    def load(
        self,
        config: SessionRiskConfig,
    ) -> RiskManager:
        if not self._path.exists():
            return RiskManager(config)

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
            raise ValueError(
                "Risk-state file could not be read."
            ) from exc

        if not isinstance(payload, dict):
            raise ValueError(
                "Risk-state file must contain a JSON object."
            )

        return RiskManager.from_state(
            config=config,
            payload=payload,
        )

    def save(
        self,
        manager: RiskManager,
    ) -> None:
        self._path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_path = self._path.with_suffix(
            self._path.suffix + ".tmp"
        )

        temporary_path.write_text(
            json.dumps(
                manager.export_state(),
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        temporary_path.replace(
            self._path
        )
