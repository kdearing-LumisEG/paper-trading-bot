"""Tests for one-shot market-signal CLI behavior."""

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import trading_bot.main as main_module
from trading_bot.broker.models import (
    AccountSnapshot,
)

from trading_bot.main import (
    build_parser,
)
from trading_bot.runtime.reconciliation import (
    ReconciliationIssue,
    ReconciliationIssueCode,
    ReconciliationReport,
)


def test_run_once_defaults_to_dry_run() -> None:
    arguments = build_parser().parse_args(
        [
            "run-once",
        ]
    )

    assert arguments.command == "run-once"
    assert arguments.execute is False
    assert arguments.force is False


def test_run_once_requires_explicit_execution() -> None:
    arguments = build_parser().parse_args(
        [
            "run-once",
            "--execute",
            "--force",
        ]
    )

    assert arguments.execute is True
    assert arguments.force is True


def test_reconciliation_failure_blocks_run_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = SimpleNamespace(
        symbol="SPY",
        paper_execution=SimpleNamespace(
            max_daily_loss=None,
            max_trades_per_session=None,
            max_consecutive_losses=None,
            risk_state_path=(
                tmp_path / "risk.json"
            ),
        ),
        reconciliation=SimpleNamespace(
            process_lock_path=(
                tmp_path / "runtime.lock"
            ),
            position_state_path=(
                tmp_path / "positions.json"
            ),
        ),
    )
    report = ReconciliationReport(
        checked_at=datetime(
            2026,
            7,
            21,
            tzinfo=timezone.utc,
        ),
        symbol="SPY",
        safe=False,
        adopted=False,
        account=AccountSnapshot(
            account_id="paper-account",
            cash=1000.0,
            buying_power=1000.0,
            equity=1000.0,
            trading_blocked=False,
            account_blocked=False,
        ),
        broker_positions=[],
        open_orders=[],
        tracked_position=None,
        issues=[
            ReconciliationIssue(
                code=(
                    ReconciliationIssueCode
                    .UNTRACKED_POSITION
                ),
                message=(
                    "Broker state is uncertain."
                ),
                symbol="SPY",
            )
        ],
    )

    class UnsafeReconciler:
        def run(
            self,
        ) -> ReconciliationReport:
            return report

    output: list[object] = []
    monkeypatch.setattr(
        main_module,
        "load_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        main_module,
        "_execution_service",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        main_module,
        "_reconciliation_service",
        lambda **kwargs: UnsafeReconciler(),
    )
    monkeypatch.setattr(
        main_module,
        "MarketSignalCycle",
        lambda **kwargs: pytest.fail(
            "run-once continued after unsafe reconciliation"
        ),
    )
    monkeypatch.setattr(
        main_module,
        "_print_json",
        output.append,
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "trading-bot",
            "run-once",
        ],
    )

    main_module.main()

    assert output[0]["outcome"] == "blocked"
    assert output[0]["reason"] == (
        "reconciliation_failed"
    )
    assert not (
        settings.reconciliation
        .process_lock_path.exists()
    )
