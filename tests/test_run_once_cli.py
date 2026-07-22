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
from trading_bot.config import (
    PaperExecutionSettings,
    ReconciliationSettings,
    Settings,
    StrategySettings,
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
            order_state_path=(
                tmp_path / "orders.json"
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


@pytest.mark.parametrize("command", ["buy", "sell"])
def test_manual_execute_is_structurally_blocked_without_mutation(
    command: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = Settings(
        alpaca_api_key="test-key",
        alpaca_secret_key="test-secret",
        symbol="SPY",
        timeframe_minutes=15,
        data_feed="iex",
        strategy=StrategySettings(fast_ema=9, slow_ema=21),
        paper_execution=PaperExecutionSettings(
            risk_state_path=tmp_path / "risk.json",
            order_state_path=tmp_path / "orders.json",
        ),
        reconciliation=ReconciliationSettings(
            process_lock_path=tmp_path / "runtime.lock",
            position_state_path=tmp_path / "positions.json",
        ),
    )
    safe_report = ReconciliationReport(
        checked_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
        symbol="SPY",
        safe=True,
        adopted=False,
        account=AccountSnapshot(
            account_id="paper-account",
            cash=1000,
            buying_power=1000,
            equity=1000,
            trading_blocked=False,
            account_blocked=False,
        ),
        broker_positions=[],
        open_orders=[],
        tracked_position=None,
        issues=[],
    )

    class NoMutationService:
        def execute_market_order(self, *args, **kwargs):
            del args, kwargs
            pytest.fail("manual execute reached broker mutation")

    class SafeReconciler:
        def run(self) -> ReconciliationReport:
            return safe_report

    output: list[object] = []
    monkeypatch.setattr(main_module, "load_settings", lambda: settings)
    monkeypatch.setattr(
        main_module,
        "_execution_service",
        lambda **kwargs: NoMutationService(),
    )
    monkeypatch.setattr(
        main_module,
        "_reconciliation_service",
        lambda **kwargs: SafeReconciler(),
    )
    monkeypatch.setattr(main_module, "_print_json", output.append)
    monkeypatch.setattr(
        "sys.argv",
        [
            "trading-bot",
            command,
            "--quantity",
            "1",
            "--client-order-id",
            "manual-test",
            "--execute",
        ],
    )

    main_module.main()

    assert output == [
        {
            "outcome": "blocked",
            "reason": "manual_execution_disabled",
            "message": (
                "Manual broker-mutating commands are disabled for the "
                "Paper Execution Core MVP."
            ),
        }
    ]
