"""Shared reconciliation-first operation for one strategy cycle."""

from dataclasses import dataclass

from trading_bot.execution.signal_models import SignalHandlingOutcome
from trading_bot.runtime.cycle import MarketSignalCycle, MarketSignalCycleResult
from trading_bot.runtime.reconciliation import (
    ReconciliationReport,
    ReconciliationService,
)


@dataclass(frozen=True)
class RuntimeCycleResult:
    reconciliation: ReconciliationReport
    cycle: MarketSignalCycleResult | None
    post_order_reconciliation: ReconciliationReport | None = None

    @property
    def safe(self) -> bool:
        return self.reconciliation.safe and (
            self.post_order_reconciliation is None
            or self.post_order_reconciliation.safe
        )


class RuntimeCycleOperation:
    """Run one cycle while the caller owns the process lock."""

    def __init__(
        self, reconciler: ReconciliationService, cycle: MarketSignalCycle
    ) -> None:
        self._reconciler = reconciler
        self._cycle = cycle

    def run(self, *, force: bool = False) -> RuntimeCycleResult:
        report = self._reconciler.run()
        if not report.safe:
            return RuntimeCycleResult(report, None)
        cycle = self._cycle.run(force=force)
        handled = cycle.signal_result
        post = None
        if (
            handled is not None
            and handled.outcome is SignalHandlingOutcome.ORDER_ATTEMPTED
        ):
            post = self._reconciler.run()
        return RuntimeCycleResult(report, cycle, post)
