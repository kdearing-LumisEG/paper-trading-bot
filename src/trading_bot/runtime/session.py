"""Autonomous, manually launched Alpaca paper-session state machine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import math
import time
from typing import Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

from trading_bot.execution.models import ExecutionOutcome
from trading_bot.execution.signal_models import StrategySignal, StrategySignalEvent
from trading_bot.runtime.cycle import MarketSignalCycleOutcome
from trading_bot.runtime.cycle_operation import RuntimeCycleOperation
from trading_bot.runtime.process_lock import FileProcessLock
from trading_bot.runtime.reconciliation import ReconciliationService
from trading_bot.runtime.session_reporting import (
    SessionEventLogger,
    SessionReportWriter,
    SessionStatusWriter,
)


class SessionState(str, Enum):
    INITIALIZING = "initializing"
    WAITING_FOR_OPEN = "waiting_for_open"
    RUNNING = "running"
    RECOVERY = "recovery"
    FLATTENING = "flattening"
    FINALIZING = "finalizing"
    COMPLETE = "complete"
    REQUIRES_REVIEW = "requires_review"


@dataclass(frozen=True)
class AutonomousSessionSettings:
    poll_seconds: float = 30.0
    preopen_wait_max_minutes: int = 180
    recovery_poll_seconds: float = 15.0
    recovery_timeout_seconds: float = 300.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.poll_seconds) or not 5 <= self.poll_seconds <= 300:
            raise ValueError("poll_seconds must be finite and between 5 and 300")
        if self.preopen_wait_max_minutes <= 0:
            raise ValueError("preopen_wait_max_minutes must be positive")
        if (
            not math.isfinite(self.recovery_poll_seconds)
            or self.recovery_poll_seconds <= 0
        ):
            raise ValueError("recovery_poll_seconds must be finite and positive")
        if (
            not math.isfinite(self.recovery_timeout_seconds)
            or self.recovery_timeout_seconds < self.recovery_poll_seconds
        ):
            raise ValueError(
                "recovery_timeout_seconds must be finite and at least recovery_poll_seconds"
            )


@dataclass
class SessionRunResult:
    session_run_id: str
    result_status: str = "configuration_failure"
    stop_reason: str = "unexpected_error"
    report_json_path: str | None = None
    report_markdown_path: str | None = None
    final_reconciliation_safe: bool = False
    requires_operator_review: bool = False
    final_position_phase: str | None = None
    final_position_quantity: float | None = None
    runtime_lock_released: bool = False


@dataclass
class _Facts:
    started_at: datetime
    state: SessionState = SessionState.INITIALIZING
    market_open: datetime | None = None
    market_close: datetime | None = None
    waited_for_open: bool = False
    polls: int = 0
    cycles: int = 0
    completed_bars: int = 0
    duplicates: int = 0
    holds: int = 0
    entries: int = 0
    exits: int = 0
    session_flattens: int = 0
    emergency_flattens: int = 0
    operator_flattens: int = 0
    recovery_attempts: int = 0
    recovery_started_at: datetime | None = None
    orders: list[dict[str, object]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    last_bar: datetime | None = None
    last_signal: str | None = None
    paper_verified: bool = False


class AutonomousSessionRunner:
    def __init__(
        self,
        *,
        settings: AutonomousSessionSettings,
        strategy_name: str,
        symbol: str,
        timeframe_minutes: int,
        starting_commit: str,
        process_lock: FileProcessLock,
        reconciler: ReconciliationService,
        operation: RuntimeCycleOperation,
        clock_source,
        signal_handler,
        event_logger: SessionEventLogger,
        status_writer: SessionStatusWriter,
        report_writer: SessionReportWriter,
        now: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        session_id_factory: Callable[[], str] = lambda: uuid4().hex,
    ) -> None:
        self.settings = settings
        self.strategy_name = strategy_name
        self.symbol = symbol
        self.timeframe = timeframe_minutes
        self.starting_commit = starting_commit
        self.lock = process_lock
        self.reconciler = reconciler
        self.operation = operation
        self.clock_source = clock_source
        self.signal_handler = signal_handler
        self.event_logger = event_logger
        self.status_writer = status_writer
        self.report_writer = report_writer
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.sleeper = sleeper
        self.session_id_factory = session_id_factory

    def _event(self, run_id: str, facts: _Facts, event_type: str, **extra) -> None:
        payload = {
            "event_version": 1,
            "event_type": event_type,
            "session_run_id": run_id,
            "timestamp": self.now(),
            "session_state": facts.state,
            "strategy_name": self.strategy_name,
            "symbol": self.symbol,
            "cycle_number": facts.cycles,
            "market_status": extra.pop("market_status", None),
            "bar_identity": None,
            "signal": None,
            "intent_id": None,
            "client_order_id": None,
            "broker_order_id": None,
            "position_generation_id": None,
            "position_phase": None,
            "position_quantity": None,
            "status": None,
            "reason": None,
            "error_type": None,
        }
        payload.update(extra)
        try:
            self.event_logger.log(payload)
        except OSError as exc:
            facts.errors.append({"type": "logging_error", "message": str(exc)})

    def _status(self, run_id: str, facts: _Facts, report=None, **extra) -> None:
        tracked = report.tracked_position if report is not None else None
        payload = {
            "schema_version": 1,
            "session_run_id": run_id,
            "updated_at": self.now(),
            "session_state": facts.state,
            "strategy_name": self.strategy_name,
            "symbol": self.symbol,
            "cycle_number": facts.cycles,
            "last_completed_bar": facts.last_bar,
            "last_signal": facts.last_signal,
            "position_phase": tracked.phase if tracked else None,
            "position_quantity": tracked.quantity if tracked else None,
            "open_broker_order_count": len(report.open_orders) if report else None,
            "unresolved_intent_count": len(report.unresolved_order_intents)
            if report
            else None,
            "reconciliation_safe": report.safe if report else None,
            "requires_operator_review": facts.state is SessionState.REQUIRES_REVIEW,
        }
        payload.update(extra)
        try:
            self.status_writer.write(payload)
        except OSError as exc:
            facts.errors.append(
                {
                    "type": "logging_error",
                    "message": str(exc),
                }
            )

    def _same_day_wait_allowed(self, clock) -> bool:
        eastern = ZoneInfo("America/New_York")
        now_ny = clock.timestamp.astimezone(eastern)
        open_ny = clock.next_open.astimezone(eastern)
        delay = clock.next_open - clock.timestamp
        return (
            open_ny.date() == now_ny.date()
            and now_ny.weekday() < 5
            and timedelta(0)
            < delay
            <= timedelta(minutes=self.settings.preopen_wait_max_minutes)
        )

    def _capture_cycle(self, facts: _Facts, cycle) -> None:
        facts.completed_bars += cycle.completed_bar_count
        facts.last_bar = cycle.latest_bar_end
        signal = (
            cycle.signal_event.signal if cycle.signal_event else cycle.generated_signal
        )
        facts.last_signal = signal.value if signal else None
        if cycle.outcome is MarketSignalCycleOutcome.DUPLICATE:
            facts.duplicates += 1
        if signal is StrategySignal.HOLD:
            facts.holds += 1
        elif signal is StrategySignal.ENTER_LONG:
            facts.entries += 1
        elif signal is StrategySignal.EXIT_LONG:
            facts.exits += 1
        if cycle.forced_session_flatten:
            facts.session_flattens += 1
        handled = cycle.signal_result
        execution = handled.execution_result if handled else None
        if execution is not None:
            order = execution.order
            facts.orders.append(
                {
                    "intent_id": execution.intent_id,
                    "client_order_id": order.client_order_id
                    if order
                    else execution.request.client_order_id,
                    "broker_order_id": order.order_id if order else None,
                    "side": execution.request.side.value,
                    "quantity": execution.request.quantity,
                    "lifecycle": execution.lifecycle_state,
                    "outcome": execution.outcome.value,
                    "fill_quantity": order.filled_quantity if order else 0,
                    "average_fill_price": order.filled_average_price if order else None,
                    "cancellation_requested": execution.cancellation_requested,
                }
            )

    def _recover(self, run_id: str, facts: _Facts):
        facts.state = SessionState.RECOVERY
        if facts.recovery_started_at is None:
            facts.recovery_started_at = self.now()
        deadline = facts.recovery_started_at + timedelta(
            seconds=self.settings.recovery_timeout_seconds
        )
        self._event(run_id, facts, "recovery_started", status="active")
        while self.now() <= deadline:
            facts.recovery_attempts += 1
            self.sleeper(self.settings.recovery_poll_seconds)
            try:
                report = self.reconciler.run()
                self._event(
                    run_id,
                    facts,
                    "recovery_attempted",
                    status="safe" if report.safe else "unsafe",
                )
                if report.safe:
                    clock = self.clock_source.get_clock()
                    if clock.is_open:
                        self._event(run_id, facts, "recovery_succeeded", status="safe")
                        facts.state = SessionState.RUNNING
                        return report
                    return report
            except Exception as exc:
                facts.errors.append({"type": type(exc).__name__, "message": str(exc)})
        self._event(run_id, facts, "recovery_timed_out", status="failed")
        return None

    @staticmethod
    def _certain_open(report) -> bool:
        tracked = report.tracked_position
        return bool(
            report.safe
            and tracked is not None
            and tracked.quantity > 0
            and tracked.position_generation_id
            and not tracked.legacy_open
            and not report.open_orders
            and not report.unknown_broker_orders
            and not report.unresolved_order_intents
        )

    def _flatten(self, run_id: str, facts: _Facts, report, action: str):
        if not self._certain_open(report):
            self._event(run_id, facts, f"{action}_blocked", status="uncertain")
            return False
        facts.state = SessionState.FLATTENING
        tracked = report.tracked_position
        identity_time = tracked.entry_filled_at or tracked.updated_at
        handled = self.signal_handler.handle(
            StrategySignalEvent(
                strategy_name=self.strategy_name,
                symbol=self.symbol,
                signal=StrategySignal.EXIT_LONG,
                signal_time=self.now(),
                timeframe_minutes=self.timeframe,
                action=action,
                identity_time=identity_time,
            )
        )
        if action == "emergency_flatten":
            facts.emergency_flattens += 1
        else:
            facts.operator_flattens += 1
        execution = handled.execution_result
        post = self.reconciler.run()
        return bool(
            execution
            and execution.outcome is ExecutionOutcome.FILLED
            and post.safe
            and (post.tracked_position is None or post.tracked_position.quantity == 0)
        )

    def run(self, *, execute: bool) -> SessionRunResult:
        run_id = self.session_id_factory()
        result = SessionRunResult(run_id)
        facts = _Facts(started_at=self.now(), paper_verified=execute)
        final_report = None
        self.lock.acquire()
        try:
            if execute:
                verification = self.clock_source.verify_paper_environment()
                if not verification.verified:
                    raise RuntimeError(verification.message)
                facts.paper_verified = True
            startup = self.reconciler.run()
            self._event(
                run_id,
                facts,
                "session_started",
                status="safe" if startup.safe else "unsafe",
            )
            if not startup.safe:
                result.stop_reason = "startup_reconciliation_failed"
                result.requires_operator_review = True
            else:
                clock = self.clock_source.get_clock()
                facts.market_open, facts.market_close = (
                    clock.next_open,
                    clock.next_close,
                )
                while not clock.is_open and self._same_day_wait_allowed(clock):
                    facts.waited_for_open = True
                    facts.state = SessionState.WAITING_FOR_OPEN
                    self._status(
                        run_id,
                        facts,
                        startup,
                        market_is_open=False,
                        next_market_open=clock.next_open,
                    )
                    self._event(
                        run_id, facts, "waiting_for_market_open", status="waiting"
                    )
                    self.sleeper(
                        min(
                            self.settings.poll_seconds,
                            max(0, (clock.next_open - clock.timestamp).total_seconds()),
                        )
                    )
                    changed = self.clock_source.get_clock()
                    if changed.next_open != clock.next_open and not changed.is_open:
                        result.stop_reason = "market_schedule_changed"
                        break
                    clock = changed
                if not clock.is_open:
                    result.result_status = "no_session_today"
                    result.stop_reason = (
                        result.stop_reason
                        if result.stop_reason != "unexpected_error"
                        else "no_usable_session"
                    )
                else:
                    facts.state = SessionState.RUNNING
                    self._event(run_id, facts, "market_opened", status="open")
                    while True:
                        try:
                            clock = self.clock_source.get_clock()
                            if not clock.is_open:
                                result.stop_reason = "market_session_ended"
                                break
                            facts.polls += 1
                            facts.cycles += 1
                            operation = self.operation.run()
                            if not operation.safe:
                                result.stop_reason = "unsafe_reconciliation"
                                result.requires_operator_review = True
                                break
                            if operation.cycle:
                                self._capture_cycle(facts, operation.cycle)
                                self._event(
                                    run_id,
                                    facts,
                                    "cycle_completed",
                                    status=operation.cycle.outcome.value,
                                    bar_identity=operation.cycle.latest_bar_end,
                                    signal=operation.cycle.generated_signal,
                                )
                            facts.recovery_started_at = None
                            self._status(
                                run_id,
                                facts,
                                operation.post_order_reconciliation
                                or operation.reconciliation,
                                market_is_open=True,
                                next_market_close=clock.next_close,
                            )
                            self.sleeper(self.settings.poll_seconds)
                        except KeyboardInterrupt:
                            raise
                        except Exception as exc:
                            facts.errors.append(
                                {"type": type(exc).__name__, "message": str(exc)}
                            )
                            recovered = self._recover(run_id, facts)
                            if recovered is not None and recovered.safe:
                                continue
                            result.stop_reason = "recovery_timeout"
                            result.requires_operator_review = True
                            emergency_report = None
                            try:
                                emergency_report = self.reconciler.run()
                            except Exception as recovery_error:
                                facts.errors.append(
                                    {
                                        "type": type(recovery_error).__name__,
                                        "message": str(recovery_error),
                                    }
                                )
                            if (
                                execute
                                and emergency_report is not None
                                and self._certain_open(emergency_report)
                            ):
                                if self._flatten(
                                    run_id,
                                    facts,
                                    emergency_report,
                                    "emergency_flatten",
                                ):
                                    result.requires_operator_review = False
                                    result.stop_reason = "emergency_flattened"
                            break
                    if not result.requires_operator_review:
                        result.result_status = "completed_flat"
        except KeyboardInterrupt:
            self._event(
                run_id, facts, "operator_shutdown_requested", status="requested"
            )
            try:
                report = self.reconciler.run()
                if execute and self._certain_open(report):
                    flattened = self._flatten(
                        run_id, facts, report, "operator_shutdown_flatten"
                    )
                    result.requires_operator_review = not flattened
                    result.stop_reason = (
                        "operator_shutdown_flattened"
                        if flattened
                        else "operator_shutdown_uncertain"
                    )
                elif report.safe and (
                    report.tracked_position is None
                    or report.tracked_position.quantity == 0
                ):
                    result.stop_reason = "operator_interrupt_flat"
                    result.result_status = "stopped_safe_flat"
                else:
                    result.requires_operator_review = True
                    result.stop_reason = "operator_shutdown_uncertain"
            except Exception as exc:
                facts.errors.append({"type": type(exc).__name__, "message": str(exc)})
                result.requires_operator_review = True
        except Exception as exc:
            facts.errors.append({"type": type(exc).__name__, "message": str(exc)})
            result.stop_reason = "startup_error"
            result.requires_operator_review = True
        finally:
            facts.state = SessionState.FINALIZING
            self._event(run_id, facts, "finalization_started", status="active")
            try:
                final_report = self.reconciler.run()
                result.final_reconciliation_safe = final_report.safe
                tracked = final_report.tracked_position
                result.final_position_phase = (
                    tracked.phase.value if tracked and tracked.phase else None
                )
                result.final_position_quantity = tracked.quantity if tracked else 0
                if not final_report.safe or (tracked and tracked.quantity > 0):
                    result.requires_operator_review = True
            except Exception as exc:
                facts.errors.append({"type": type(exc).__name__, "message": str(exc)})
                result.requires_operator_review = True
            facts.state = (
                SessionState.REQUIRES_REVIEW
                if result.requires_operator_review
                else SessionState.COMPLETE
            )
            if result.requires_operator_review:
                result.result_status = "requires_review_state_failure"
            report_payload = {
                "session_run_id": run_id,
                "session_date": facts.started_at.date(),
                "strategy_name": self.strategy_name,
                "symbol": self.symbol,
                "timeframe_minutes": self.timeframe,
                "execution_mode": "paper" if execute else "dry_run",
                "starting_commit": self.starting_commit,
                "started_at": facts.started_at,
                "ended_at": self.now(),
                "market_open": facts.market_open,
                "market_close": facts.market_close,
                "waited_for_open": facts.waited_for_open,
                "polls": facts.polls,
                "cycles_attempted": facts.cycles,
                "completed_bars_evaluated": facts.completed_bars,
                "duplicate_bars_skipped": facts.duplicates,
                "hold_decisions": facts.holds,
                "entry_signals": facts.entries,
                "exit_signals": facts.exits,
                "session_flatten_signals": facts.session_flattens,
                "emergency_flatten_signals": facts.emergency_flattens,
                "operator_shutdown_signals": facts.operator_flattens,
                "orders": facts.orders,
                "recovery_attempts": facts.recovery_attempts,
                "errors": facts.errors,
                "paper_environment_verified": facts.paper_verified,
                "final_reconciliation_safe": result.final_reconciliation_safe,
                "final_position_phase": result.final_position_phase,
                "final_position_quantity": result.final_position_quantity,
                "open_broker_orders": len(final_report.open_orders)
                if final_report
                else None,
                "unknown_broker_orders": len(final_report.unknown_broker_orders)
                if final_report
                else None,
                "unresolved_intents": len(final_report.unresolved_order_intents)
                if final_report
                else None,
                "runtime_lock_released": True,
                "session_status": result.result_status,
                "stop_reason": result.stop_reason,
                "required_operator_action": "Review broker and durable state before restarting"
                if result.requires_operator_review
                else None,
            }
            try:
                json_path, md_path = self.report_writer.write(
                    report_payload, urgent=result.requires_operator_review
                )
                result.report_json_path, result.report_markdown_path = (
                    str(json_path),
                    str(md_path),
                )
            except (OSError, FileExistsError) as exc:
                facts.errors.append(
                    {
                        "type": "reporting_error",
                        "message": str(exc),
                    }
                )
                result.requires_operator_review = True
                result.result_status = "requires_review_state_failure"
                result.report_json_path = None
                result.report_markdown_path = None
            finally:
                self.lock.release()
                result.runtime_lock_released = True
            self._status(
                run_id,
                facts,
                final_report,
                stop_reason=result.stop_reason,
                report_path=result.report_json_path,
                market_is_open=False,
            )
            self._event(
                run_id,
                facts,
                "session_requires_review"
                if result.requires_operator_review
                else "session_completed",
                status=result.result_status,
                reason=result.stop_reason,
            )
        return result
