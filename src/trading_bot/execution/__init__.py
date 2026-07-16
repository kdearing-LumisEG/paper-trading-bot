"""Safe paper-order and signal-execution components."""

from trading_bot.execution.client_ids import (
    build_signal_client_order_id,
)
from trading_bot.execution.coordinator import (
    SignalExecutionCoordinator,
)
from trading_bot.execution.decision_logging import (
    JsonlSignalDecisionLogger,
    NullSignalDecisionLogger,
)
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
from trading_bot.execution.risk_state import (
    JsonRiskStateStore,
    NullRiskStateStore,
)
from trading_bot.execution.service import (
    PaperExecutionService,
)
from trading_bot.execution.signal_models import (
    SignalHandlingOutcome,
    SignalHandlingResult,
    StrategySignal,
    StrategySignalEvent,
)

__all__ = [
    "ExecutionOutcome",
    "ExecutionResult",
    "ExecutionSettings",
    "FileKillSwitch",
    "JsonRiskStateStore",
    "JsonlExecutionLogger",
    "JsonlSignalDecisionLogger",
    "NullRiskStateStore",
    "NullSignalDecisionLogger",
    "PaperExecutionService",
    "SignalExecutionCoordinator",
    "SignalHandlingOutcome",
    "SignalHandlingResult",
    "StaticKillSwitch",
    "StrategySignal",
    "StrategySignalEvent",
    "build_signal_client_order_id",
]
