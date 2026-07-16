"""Safe paper-order execution components."""

from trading_bot.execution.kill_switch import (
    FileKillSwitch,
    StaticKillSwitch,
)
from trading_bot.execution.logging import (
    JsonlExecutionLogger,
)
from trading_bot.execution.models import (
    ExecutionOutcome,
    ExecutionResult,
    ExecutionSettings,
)
from trading_bot.execution.service import (
    PaperExecutionService,
)

__all__ = [
    "ExecutionOutcome",
    "ExecutionResult",
    "ExecutionSettings",
    "FileKillSwitch",
    "JsonlExecutionLogger",
    "PaperExecutionService",
    "StaticKillSwitch",
]
