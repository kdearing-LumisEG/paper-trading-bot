"""Deterministic tests for autonomous session state and lock lifecycle."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from trading_bot.broker.models import MarketClockSnapshot
from trading_bot.runtime.process_lock import FileProcessLock
from trading_bot.runtime.session import (
    AutonomousSessionRunner,
    AutonomousSessionSettings,
)
from trading_bot.runtime.session_reporting import (
    SessionEventLogger,
    SessionReportWriter,
    SessionStatusWriter,
)


NOW = datetime(2026, 7, 22, 22, 0, tzinfo=timezone.utc)


class ClosedClock:
    def get_clock(self):
        return MarketClockSnapshot(
            timestamp=NOW,
            is_open=False,
            next_open=NOW + timedelta(hours=15),
            next_close=NOW + timedelta(hours=21, minutes=30),
        )


class SafeReconciler:
    def __init__(self) -> None:
        self.calls = 0

    def run(self):
        self.calls += 1
        return SimpleNamespace(
            safe=True,
            tracked_position=None,
            open_orders=[],
            unknown_broker_orders=[],
            unresolved_order_intents=[],
        )


class NeverOperation:
    def run(self):
        pytest.fail("closed-market session evaluated a strategy cycle")


class SequenceClock:
    def __init__(self, snapshots) -> None:
        self.snapshots = list(snapshots)
        self.last = self.snapshots[-1]

    def get_clock(self):
        if self.snapshots:
            self.last = self.snapshots.pop(0)
        return self.last


class SafeOperation:
    def __init__(self) -> None:
        self.calls = 0

    def run(self):
        self.calls += 1
        report = SafeReconciler().run()
        return SimpleNamespace(
            safe=True,
            reconciliation=report,
            post_order_reconciliation=None,
            cycle=None,
        )


def market_clock(*, is_open: bool, at: datetime = NOW):
    return MarketClockSnapshot(
        timestamp=at,
        is_open=is_open,
        next_open=at + timedelta(days=1) if not is_open else at + timedelta(days=1),
        next_close=at + timedelta(hours=1),
    )


def build_runner(
    tmp_path: Path,
    *,
    clock,
    operation,
    sleeper,
    reconciler=None,
    status_writer=None,
    report_writer=None,
    now=lambda: NOW,
):
    return AutonomousSessionRunner(
        settings=AutonomousSessionSettings(
            poll_seconds=5,
            recovery_poll_seconds=5,
            recovery_timeout_seconds=10,
        ),
        strategy_name="ema_crossover_9_21",
        symbol="SPY",
        timeframe_minutes=15,
        starting_commit="abc123",
        process_lock=FileProcessLock(tmp_path / "runtime.lock"),
        reconciler=reconciler or SafeReconciler(),
        operation=operation,
        clock_source=clock,
        signal_handler=object(),
        event_logger=SessionEventLogger(tmp_path / "events.jsonl"),
        status_writer=status_writer or SessionStatusWriter(tmp_path / "status.json"),
        report_writer=report_writer or SessionReportWriter(tmp_path / "reports"),
        now=now,
        sleeper=sleeper,
        session_id_factory=lambda: "expanded-session",
    )


def test_closed_market_writes_no_session_report_without_sleep(tmp_path: Path) -> None:
    sleeps = []
    lock = FileProcessLock(tmp_path / "runtime.lock")
    reconciler = SafeReconciler()
    runner = AutonomousSessionRunner(
        settings=AutonomousSessionSettings(),
        strategy_name="ema_crossover_9_21",
        symbol="SPY",
        timeframe_minutes=15,
        starting_commit="abc123",
        process_lock=lock,
        reconciler=reconciler,
        operation=NeverOperation(),
        clock_source=ClosedClock(),
        signal_handler=object(),
        event_logger=SessionEventLogger(tmp_path / "events.jsonl"),
        status_writer=SessionStatusWriter(tmp_path / "status.json"),
        report_writer=SessionReportWriter(tmp_path / "reports"),
        now=lambda: NOW,
        sleeper=sleeps.append,
        session_id_factory=lambda: "fixed-session",
    )
    result = runner.run(execute=False)
    assert result.result_status == "no_session_today"
    assert result.runtime_lock_released
    assert not lock.path.exists()
    assert not sleeps
    assert Path(result.report_json_path).exists()
    assert reconciler.calls == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"poll_seconds": 4.9},
        {"poll_seconds": 301},
        {"recovery_poll_seconds": 0},
        {"recovery_poll_seconds": 20, "recovery_timeout_seconds": 10},
    ],
)
def test_session_settings_reject_unsafe_timing(kwargs) -> None:
    with pytest.raises(ValueError):
        AutonomousSessionSettings(**kwargs)


def test_market_close_returns_automatically_and_releases_lock(tmp_path: Path) -> None:
    operation = SafeOperation()
    clock = SequenceClock(
        [
            market_clock(is_open=True),
            market_clock(is_open=True),
            market_clock(is_open=False),
        ]
    )
    runner = build_runner(
        tmp_path, clock=clock, operation=operation, sleeper=lambda _: None
    )
    result = runner.run(execute=False)
    assert operation.calls == 1
    assert result.stop_reason == "market_session_ended"
    assert result.runtime_lock_released
    assert Path(result.report_json_path).exists()
    assert not (tmp_path / "runtime.lock").exists()


def test_interrupt_while_running_flat_reports_and_releases(tmp_path: Path) -> None:
    def interrupt(_seconds):
        raise KeyboardInterrupt

    runner = build_runner(
        tmp_path,
        clock=SequenceClock([market_clock(is_open=True), market_clock(is_open=True)]),
        operation=SafeOperation(),
        sleeper=interrupt,
    )
    result = runner.run(execute=False)
    assert result.stop_reason == "operator_interrupt_flat"
    assert result.result_status == "stopped_safe_flat"
    assert result.runtime_lock_released
    assert Path(result.report_markdown_path).exists()


def test_status_failure_is_logging_only_and_does_not_block_close(
    tmp_path: Path,
) -> None:
    class FailingStatus:
        def write(self, payload):
            del payload
            raise OSError("status unavailable")

    runner = build_runner(
        tmp_path,
        clock=SequenceClock(
            [
                market_clock(is_open=True),
                market_clock(is_open=True),
                market_clock(is_open=False),
            ]
        ),
        operation=SafeOperation(),
        sleeper=lambda _: None,
        status_writer=FailingStatus(),
    )
    result = runner.run(execute=False)
    assert result.result_status == "completed_flat"
    assert result.report_json_path is not None
    assert result.runtime_lock_released


def test_report_failure_returns_no_false_paths_and_releases_lock(
    tmp_path: Path,
) -> None:
    class FailingReports:
        def write(self, payload, *, urgent=False):
            del payload, urgent
            raise OSError("report unavailable")

    runner = build_runner(
        tmp_path,
        clock=ClosedClock(),
        operation=NeverOperation(),
        sleeper=lambda _: None,
        report_writer=FailingReports(),
    )
    result = runner.run(execute=False)
    assert result.requires_operator_review
    assert result.report_json_path is None
    assert result.report_markdown_path is None
    assert result.runtime_lock_released
    assert not (tmp_path / "runtime.lock").exists()


def test_recovery_deadline_is_cumulative(tmp_path: Path) -> None:
    class FailingReconciler:
        def run(self):
            raise OSError("temporary read failure")

    current = [NOW]

    def now():
        return current[0]

    def advance(seconds):
        current[0] += timedelta(seconds=seconds)

    runner = build_runner(
        tmp_path,
        clock=ClosedClock(),
        operation=NeverOperation(),
        sleeper=advance,
        reconciler=FailingReconciler(),
        now=now,
    )
    facts_type = __import__("trading_bot.runtime.session", fromlist=["_Facts"])._Facts
    facts = facts_type(started_at=NOW)
    assert runner._recover("recovery-session", facts) is None
    assert facts.recovery_attempts == 3
    assert current[0] > NOW + timedelta(seconds=10)


@pytest.mark.parametrize(
    "unsafe_field", ["open_orders", "unknown_broker_orders", "unresolved_order_intents"]
)
def test_ambiguous_order_state_blocks_emergency_flatten(unsafe_field) -> None:
    tracked = SimpleNamespace(
        quantity=1,
        position_generation_id="pg-known",
        legacy_open=False,
    )
    report = SimpleNamespace(
        safe=True,
        tracked_position=tracked,
        open_orders=[],
        unknown_broker_orders=[],
        unresolved_order_intents=[],
    )
    setattr(report, unsafe_field, [object()])
    assert not AutonomousSessionRunner._certain_open(report)
