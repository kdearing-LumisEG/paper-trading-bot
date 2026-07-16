"""Emergency controls that can block new paper orders."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class KillSwitch(Protocol):
    """Interface for determining whether execution is disabled."""

    def is_active(self) -> bool:
        """Return whether new orders must be blocked."""


@dataclass(frozen=True)
class FileKillSwitch:
    """Activate the kill switch whenever a marker file exists."""

    path: Path = Path("STOP_TRADING")

    def is_active(self) -> bool:
        return self.path.exists()


@dataclass(frozen=True)
class StaticKillSwitch:
    """Simple switch useful for tests and manual wiring."""

    active: bool = False

    def is_active(self) -> bool:
        return self.active
