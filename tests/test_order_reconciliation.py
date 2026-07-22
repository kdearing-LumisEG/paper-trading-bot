"""Intent-aware broker reconciliation and restart recovery tests."""

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from trading_bot.broker.models import (
    AccountSnapshot,
    BrokerErrorKind,
    BrokerExecutionError,
    BrokerOrder,
    BrokerOrderStatus,
    MarketOrderRequest,
    OrderSide,
    PaperEnvironmentStatus,
    PaperEnvironmentVerification,
    PositionSnapshot,
)
from trading_bot.execution.models import ExecutionSettings
from trading_bot.execution.order_state import (
    JsonOrderStateStore,
    OrderIntent,
    OrderLifecycleState,
)
from trading_bot.execution.position_state import (
    JsonPositionStateStore,
    PositionPhase,
    TrackedPosition,
)
from trading_bot.execution.service import PaperExecutionService
from trading_bot.runtime.reconciliation import (
    ReconciliationIssueCode,
    ReconciliationService,
)


NOW = datetime(2026, 7, 21, 20, 0, tzinfo=timezone.utc)


def intent(
    *,
    side: OrderSide = OrderSide.BUY,
    state: OrderLifecycleState = OrderLifecycleState.ACCEPTED,
) -> OrderIntent:
    return OrderIntent(
        intent_id=f"{side.value}-intent",
        strategy_name="ema_9_21",
        symbol="SPY",
        timeframe_minutes=15,
        signal_bar_end=NOW,
        action="enter_long" if side is OrderSide.BUY else "exit_long",
        side=side,
        requested_quantity=2,
        client_order_id=f"{side.value}-client",
        position_generation_id="pg-owned",
        lifecycle_state=state,
        created_at=NOW,
        updated_at=NOW,
        broker_order_id="broker-1",
    )


def order(
    status: BrokerOrderStatus,
    *,
    side: OrderSide = OrderSide.BUY,
    filled: float = 0.0,
    order_id: str = "broker-1",
) -> BrokerOrder:
    return BrokerOrder(
        order_id=order_id,
        client_order_id=f"{side.value}-client",
        symbol="SPY",
        quantity=2,
        side=side,
        status=status,
        filled_quantity=filled,
        filled_average_price=501.25 if filled else None,
        submitted_at=NOW,
    )


class ReconciliationBroker:
    def __init__(self) -> None:
        self.account = AccountSnapshot(
            account_id="paper-account",
            cash=10_000,
            buying_power=20_000,
            equity=10_000,
            trading_blocked=False,
            account_blocked=False,
        )
        self.positions: list[PositionSnapshot] = []
        self.open_orders: list[BrokerOrder] = []
        self.lookup: BrokerOrder | None = None
        self.lookup_error: BrokerExecutionError | None = None

    def verify_paper_environment(self) -> PaperEnvironmentVerification:
        return PaperEnvironmentVerification(
            PaperEnvironmentStatus.VERIFIED_PAPER,
            "verified fake paper broker",
        )

    def find_order_by_client_id(
        self,
        client_order_id: str,
    ) -> BrokerOrder | None:
        del client_order_id
        if self.lookup_error is not None:
            raise self.lookup_error
        return self.lookup

    def list_open_orders(self) -> list[BrokerOrder]:
        return list(self.open_orders)

    def list_positions(self) -> list[PositionSnapshot]:
        return list(self.positions)

    def get_account(self) -> AccountSnapshot:
        return self.account

    def submit_market_order(
        self,
        request: MarketOrderRequest,
    ) -> BrokerOrder:
        del request
        pytest.fail("reconciliation attempted broker mutation")

    def get_order(self, order_id: str) -> BrokerOrder:
        del order_id
        pytest.fail("unexpected order-id lookup")

    def cancel_order(self, order_id: str) -> None:
        del order_id
        pytest.fail("reconciliation attempted cancellation")


def make_reconciler(
    tmp_path: Path,
    broker: ReconciliationBroker,
) -> tuple[
    ReconciliationService,
    JsonOrderStateStore,
    JsonPositionStateStore,
]:
    orders = JsonOrderStateStore(tmp_path / "orders.json")
    positions = JsonPositionStateStore(tmp_path / "positions.json")
    execution = PaperExecutionService(
        broker=broker,  # type: ignore[arg-type]
        settings=ExecutionSettings(dry_run=False),
        order_state_store=orders,
        position_state_store=positions,
        now=lambda: NOW,
    )
    reconciler = ReconciliationService(
        execution_service=execution,
        position_state_store=positions,
        order_state_store=orders,
        symbol="SPY",
        now=lambda: NOW,
    )
    return reconciler, orders, positions


def broker_position(quantity: float = 2) -> PositionSnapshot:
    return PositionSnapshot(
        symbol="SPY",
        quantity=quantity,
        average_entry_price=501.25,
        market_value=quantity * 501.25,
        unrealized_pnl=0,
    )


def test_matching_open_intent_is_not_reported_unknown(
    tmp_path: Path,
) -> None:
    broker = ReconciliationBroker()
    broker.open_orders = [order(BrokerOrderStatus.ACCEPTED)]
    reconciler, orders, _ = make_reconciler(tmp_path, broker)
    orders.save(intent())

    report = reconciler.run()

    assert report.matched_order_intents == ["buy-intent"]
    assert report.unknown_broker_orders == []
    assert not report.safe
    assert ReconciliationIssueCode.UNRESOLVED_ORDER_INTENT.value in report.issue_codes


def test_uncertain_intent_resolves_to_filled_entry(
    tmp_path: Path,
) -> None:
    broker = ReconciliationBroker()
    broker.lookup = order(BrokerOrderStatus.FILLED, filled=2)
    broker.positions = [broker_position()]
    reconciler, orders, positions = make_reconciler(tmp_path, broker)
    orders.save(intent(state=OrderLifecycleState.RECONCILIATION_REQUIRED))

    report = reconciler.run()

    assert report.safe
    assert report.advanced_order_intents == ["buy-intent"]
    assert orders.load_all()[0].lifecycle_state is OrderLifecycleState.FILLED
    assert positions.load("SPY").quantity == pytest.approx(2)


def test_uncertain_absence_and_lookup_error_remain_blocked(
    tmp_path: Path,
) -> None:
    broker = ReconciliationBroker()
    reconciler, orders, _ = make_reconciler(tmp_path, broker)
    orders.save(intent(state=OrderLifecycleState.RECONCILIATION_REQUIRED))

    absent = reconciler.run()
    broker.lookup_error = BrokerExecutionError(
        BrokerErrorKind.NETWORK,
        "lookup unavailable",
    )
    failed_lookup = reconciler.run()

    assert not absent.safe
    assert absent.unresolved_order_intents == ["buy-intent"]
    assert not failed_lookup.safe
    assert orders.load_all()[0].last_error_type == "network"


def test_partial_fill_reconciles_actual_position_quantity(
    tmp_path: Path,
) -> None:
    broker = ReconciliationBroker()
    broker.open_orders = [
        order(BrokerOrderStatus.PARTIALLY_FILLED, filled=1)
    ]
    broker.positions = [broker_position(1)]
    reconciler, orders, positions = make_reconciler(tmp_path, broker)
    orders.save(intent())

    report = reconciler.run()

    assert not report.safe
    assert positions.load("SPY").quantity == pytest.approx(1)
    assert orders.load_all()[0].filled_quantity == pytest.approx(1)


def test_filled_exit_reconciles_position_to_flat(tmp_path: Path) -> None:
    broker = ReconciliationBroker()
    broker.lookup = order(
        BrokerOrderStatus.FILLED,
        side=OrderSide.SELL,
        filled=2,
    )
    reconciler, orders, positions = make_reconciler(tmp_path, broker)
    positions.save(
        TrackedPosition(
            symbol="SPY",
            strategy_name="ema_9_21",
            position_generation_id="pg-owned",
            phase=PositionPhase.OPEN,
            quantity=2,
            average_entry_price=500,
            updated_at=NOW,
            entry_intent_id="buy-intent",
        )
    )
    orders.save(intent(side=OrderSide.SELL))

    report = reconciler.run()

    assert report.safe
    assert positions.load("SPY").phase is PositionPhase.FLAT


def test_unknown_conflicting_and_multiple_broker_orders_block(
    tmp_path: Path,
) -> None:
    broker = ReconciliationBroker()
    unknown = order(BrokerOrderStatus.ACCEPTED)
    reconciler, orders, _ = make_reconciler(tmp_path, broker)
    broker.open_orders = [unknown]
    unknown_report = reconciler.run()
    assert ReconciliationIssueCode.OPEN_ORDER.value in unknown_report.issue_codes

    orders.save(intent())
    broker.open_orders = [replace(unknown, side=OrderSide.SELL)]
    conflict = reconciler.run()
    assert not conflict.safe
    assert orders.load_all()[0].lifecycle_state is (
        OrderLifecycleState.RECONCILIATION_REQUIRED
    )

    broker.open_orders = [
        unknown,
        replace(unknown, order_id="broker-2"),
    ]
    multiple = reconciler.run()
    assert ReconciliationIssueCode.ORDER_INTENT_MISMATCH.value in multiple.issue_codes


def test_malformed_order_state_is_left_untouched_and_blocks(
    tmp_path: Path,
) -> None:
    broker = ReconciliationBroker()
    reconciler, _, _ = make_reconciler(tmp_path, broker)
    state_path = tmp_path / "orders.json"
    state_path.write_text("not-json", encoding="utf-8")

    report = reconciler.run()

    assert not report.safe
    assert ReconciliationIssueCode.ORDER_STATE_INVALID.value in report.issue_codes
    assert state_path.read_text(encoding="utf-8") == "not-json"
