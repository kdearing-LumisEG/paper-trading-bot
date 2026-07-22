"""Acceptance coverage for the durable paper-order lifecycle."""

from collections import deque
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from trading_bot.broker.models import (
    BrokerErrorKind,
    BrokerExecutionError,
    BrokerOrder,
    BrokerOrderStatus,
    MarketOrderRequest,
    OrderSide,
    PaperEnvironmentStatus,
    PaperEnvironmentVerification,
)
from trading_bot.execution.logging import OrderLifecycleEvent
from trading_bot.execution.models import ExecutionOutcome, ExecutionSettings
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
from trading_bot.execution.service import (
    PaperExecutionService,
    advance_intent_from_broker_order,
)


NOW = datetime(2026, 7, 21, 20, 0, tzinfo=timezone.utc)


def broker_order(
    status: BrokerOrderStatus,
    *,
    client_order_id: str = "placeholder",
    filled_quantity: float = 0.0,
    side: OrderSide = OrderSide.BUY,
) -> BrokerOrder:
    return BrokerOrder(
        order_id="broker-1",
        client_order_id=client_order_id,
        symbol="SPY",
        quantity=2.0,
        side=side,
        status=status,
        filled_quantity=filled_quantity,
        filled_average_price=(
            501.25 if filled_quantity > 0 else None
        ),
        submitted_at=NOW,
    )


class MemoryLifecycleLogger:
    def __init__(self) -> None:
        self.events: list[OrderLifecycleEvent] = []

    def log_event(self, event: OrderLifecycleEvent) -> None:
        self.events.append(event)


class FailingLifecycleLogger:
    def log_event(self, event: OrderLifecycleEvent) -> None:
        del event
        raise OSError("audit log unavailable")


class FailOnceOrderStore(JsonOrderStateStore):
    def __init__(self, path: Path, fail_on_save: int) -> None:
        super().__init__(path)
        self.save_count = 0
        self.fail_on_save = fail_on_save

    def save(self, intent: OrderIntent) -> None:
        self.save_count += 1
        if self.save_count == self.fail_on_save:
            raise OSError("order state unavailable")
        super().save(intent)


class FailOncePositionStore(JsonPositionStateStore):
    def __init__(self, path: Path, fail_on_save: int) -> None:
        super().__init__(path)
        self.save_count = 0
        self.fail_on_save = fail_on_save

    def save(self, position: TrackedPosition) -> None:
        self.save_count += 1
        if self.save_count == self.fail_on_save:
            raise OSError("position state unavailable")
        super().save(position)


class ScenarioBroker:
    def __init__(
        self,
        *,
        submitted: BrokerOrder | None = None,
        polls: list[BrokerOrder] | None = None,
        submit_error: BrokerExecutionError | None = None,
        recovered: BrokerOrder | None = None,
        verification: PaperEnvironmentStatus = (
            PaperEnvironmentStatus.VERIFIED_PAPER
        ),
    ) -> None:
        self.submitted = submitted or broker_order(
            BrokerOrderStatus.ACCEPTED
        )
        self.polls = deque(polls or [])
        self.submit_error = submit_error
        self.recovered = recovered
        self.verification = verification
        self.submit_count = 0
        self.cancel_count = 0
        self.submit_snapshot = None
        self.order_store: JsonOrderStateStore | None = None
        self.last_request: MarketOrderRequest | None = None

    def verify_paper_environment(self) -> PaperEnvironmentVerification:
        return PaperEnvironmentVerification(
            status=self.verification,
            message=f"environment is {self.verification.value}",
        )

    def _normalize(self, order: BrokerOrder) -> BrokerOrder:
        if self.last_request is None:
            return order
        return replace(
            order,
            client_order_id=self.last_request.client_order_id,
            quantity=float(self.last_request.quantity),
            side=self.last_request.side,
        )

    def submit_market_order(
        self,
        request: MarketOrderRequest,
    ) -> BrokerOrder:
        self.submit_count += 1
        self.last_request = request
        if self.order_store is not None:
            self.submit_snapshot = self.order_store.load_all()[0]
        if self.submit_error is not None:
            raise self.submit_error
        return self._normalize(self.submitted)

    def get_order(self, order_id: str) -> BrokerOrder:
        assert order_id == "broker-1"
        order = self.polls.popleft() if self.polls else self.submitted
        return self._normalize(order)

    def find_order_by_client_id(
        self,
        client_order_id: str,
    ) -> BrokerOrder | None:
        if (
            client_order_id == "compatibility-id"
            or self.recovered is None
        ):
            return None
        self.last_request = MarketOrderRequest(
            symbol="SPY",
            quantity=2,
            side=self.recovered.side,
            client_order_id=client_order_id,
        )
        return self._normalize(self.recovered)

    def cancel_order(self, order_id: str) -> None:
        assert order_id == "broker-1"
        self.cancel_count += 1


def request(side: OrderSide = OrderSide.BUY) -> MarketOrderRequest:
    return MarketOrderRequest(
        symbol="SPY",
        quantity=2,
        side=side,
        client_order_id="compatibility-id",
    )


def service(
    broker: ScenarioBroker,
    tmp_path: Path,
    *,
    max_polls: int = 1,
    logger: MemoryLifecycleLogger | FailingLifecycleLogger | None = None,
    dry_run: bool = False,
) -> tuple[
    PaperExecutionService,
    JsonOrderStateStore,
    JsonPositionStateStore,
]:
    order_store = JsonOrderStateStore(tmp_path / "orders.json")
    position_store = JsonPositionStateStore(tmp_path / "positions.json")
    broker.order_store = order_store
    execution = PaperExecutionService(
        broker=broker,  # type: ignore[arg-type]
        settings=ExecutionSettings(
            dry_run=dry_run,
            poll_interval_seconds=0.0,
            max_poll_attempts=max_polls,
            cancel_on_timeout=True,
            cancellation_confirmation_poll_seconds=0.01,
            cancellation_confirmation_timeout_seconds=0.01,
        ),
        sleeper=lambda _: None,
        order_state_store=order_store,
        position_state_store=position_store,
        lifecycle_logger=logger,
        now=lambda: NOW,
    )
    return execution, order_store, position_store


def execute(execution: PaperExecutionService):
    return execution.execute_market_order(
        request(),
        strategy_name="ema_9_21",
        timeframe_minutes=15,
        signal_bar_end=NOW,
        action="enter_long",
    )


def test_intent_is_submitting_before_single_broker_call(
    tmp_path: Path,
) -> None:
    broker = ScenarioBroker(
        submitted=broker_order(BrokerOrderStatus.FILLED, filled_quantity=2)
    )
    execution, store, _ = service(broker, tmp_path)

    result = execute(execution)

    assert result.outcome is ExecutionOutcome.FILLED
    assert broker.submit_count == 1
    assert broker.submit_snapshot.lifecycle_state is OrderLifecycleState.SUBMITTING
    assert store.load_all()[0].lifecycle_state is OrderLifecycleState.FILLED


@pytest.mark.parametrize(
    "status, expected",
    [
        (BrokerOrderStatus.REJECTED, OrderLifecycleState.REJECTED),
        (BrokerOrderStatus.EXPIRED, OrderLifecycleState.EXPIRED),
        (BrokerOrderStatus.UNKNOWN, OrderLifecycleState.RECONCILIATION_REQUIRED),
    ],
)
def test_immediate_broker_states_are_persisted(
    tmp_path: Path,
    status: BrokerOrderStatus,
    expected: OrderLifecycleState,
) -> None:
    broker = ScenarioBroker(submitted=broker_order(status))
    execution, store, _ = service(broker, tmp_path)

    execute(execution)

    assert store.load_all()[0].lifecycle_state is expected


def test_immediate_acceptance_is_recorded_before_polling(
    tmp_path: Path,
) -> None:
    logger = MemoryLifecycleLogger()
    broker = ScenarioBroker(
        submitted=broker_order(BrokerOrderStatus.ACCEPTED),
        polls=[broker_order(BrokerOrderStatus.FILLED, filled_quantity=2)],
    )
    execution, _, _ = service(broker, tmp_path, logger=logger)

    execute(execution)

    returned = next(
        event
        for event in logger.events
        if event.event_type == "order_submission_returned"
    )
    assert returned.lifecycle_state == "accepted"


def test_partial_fill_then_fill_updates_actual_position(
    tmp_path: Path,
) -> None:
    broker = ScenarioBroker(
        submitted=broker_order(
            BrokerOrderStatus.PARTIALLY_FILLED,
            filled_quantity=1,
        ),
        polls=[broker_order(BrokerOrderStatus.FILLED, filled_quantity=2)],
    )
    execution, store, positions = service(broker, tmp_path)

    result = execute(execution)

    assert result.newly_filled_quantity == pytest.approx(2)
    assert store.load_all()[0].filled_quantity == pytest.approx(2)
    tracked = positions.load("SPY")
    assert tracked.quantity == pytest.approx(2)
    assert tracked.phase is PositionPhase.OPEN


@pytest.mark.parametrize(
    "confirmation, expected_state, expected_quantity",
    [
        (broker_order(BrokerOrderStatus.CANCELED), "canceled", 0),
        (
            broker_order(
                BrokerOrderStatus.CANCELED,
                filled_quantity=1,
            ),
            "canceled",
            1,
        ),
        (
            broker_order(BrokerOrderStatus.FILLED, filled_quantity=2),
            "filled",
            2,
        ),
        (
            broker_order(BrokerOrderStatus.ACCEPTED),
            "reconciliation_required",
            0,
        ),
    ],
)
def test_cancellation_confirmation_controls_final_state(
    tmp_path: Path,
    confirmation: BrokerOrder,
    expected_state: str,
    expected_quantity: float,
) -> None:
    broker = ScenarioBroker(
        submitted=broker_order(BrokerOrderStatus.ACCEPTED),
        polls=[
            broker_order(BrokerOrderStatus.ACCEPTED),
            confirmation,
        ],
    )
    execution, store, positions = service(broker, tmp_path)

    result = execute(execution)

    assert broker.cancel_count == 1
    assert result.lifecycle_state == expected_state
    assert store.load_all()[0].cancellation_requested_at == NOW
    assert positions.load("SPY").quantity == pytest.approx(expected_quantity)


def test_timeout_before_transmission_is_terminal_and_not_retried(
    tmp_path: Path,
) -> None:
    broker = ScenarioBroker(
        submit_error=BrokerExecutionError(
            BrokerErrorKind.TIMEOUT_BEFORE_TRANSMISSION,
            "request was not sent",
        )
    )
    execution, store, _ = service(broker, tmp_path)

    first = execute(execution)
    second = execute(execution)

    assert first.lifecycle_state == "rejected"
    assert second.lifecycle_state == "rejected"
    assert broker.submit_count == 1
    assert store.load_all()[0].last_error_type == "timeout_before_transmission"


@pytest.mark.parametrize(
    "recovered, expected",
    [
        (broker_order(BrokerOrderStatus.ACCEPTED), "accepted"),
        (
            broker_order(BrokerOrderStatus.FILLED, filled_quantity=2),
            "filled",
        ),
        (None, "reconciliation_required"),
    ],
)
def test_ambiguous_submission_uses_lookup_without_resubmit(
    tmp_path: Path,
    recovered: BrokerOrder | None,
    expected: str,
) -> None:
    broker = ScenarioBroker(
        submit_error=BrokerExecutionError(
            BrokerErrorKind.AMBIGUOUS_SUBMISSION,
            "response uncertain",
        ),
        recovered=recovered,
    )
    execution, store, _ = service(broker, tmp_path)

    result = execute(execution)

    assert result.lifecycle_state == expected
    assert broker.submit_count == 1
    assert store.load_all()[0].lifecycle_state.value == expected
    if recovered is None:
        repeated = execute(execution)
        assert repeated.lifecycle_state == "reconciliation_required"
        assert broker.submit_count == 1


def test_restart_reconciles_existing_intent_without_resubmit(
    tmp_path: Path,
) -> None:
    first_broker = ScenarioBroker(
        submit_error=BrokerExecutionError(
            BrokerErrorKind.AMBIGUOUS_SUBMISSION,
            "response uncertain",
        )
    )
    first_service, _, _ = service(first_broker, tmp_path)
    execute(first_service)

    second_broker = ScenarioBroker(
        recovered=broker_order(BrokerOrderStatus.FILLED, filled_quantity=2)
    )
    second_service, store, _ = service(second_broker, tmp_path)
    result = execute(second_service)

    assert result.lifecycle_state == "filled"
    assert second_broker.submit_count == 0
    assert store.load_all()[0].lifecycle_state is OrderLifecycleState.FILLED


def test_unresolved_other_intent_blocks_new_action(
    tmp_path: Path,
) -> None:
    broker = ScenarioBroker()
    execution, store, _ = service(broker, tmp_path)
    existing = OrderIntent(
        intent_id="other-intent",
        strategy_name="ema_9_21",
        symbol="SPY",
        timeframe_minutes=15,
        signal_bar_end=NOW,
        action="enter_long",
        side=OrderSide.BUY,
        requested_quantity=2,
        client_order_id="other-client",
        position_generation_id="other-generation",
        lifecycle_state=OrderLifecycleState.RECONCILIATION_REQUIRED,
        created_at=NOW,
        updated_at=NOW,
    )
    store.save(existing)

    result = execution.execute_market_order(
        request(),
        strategy_name="ema_9_21",
        timeframe_minutes=15,
        signal_bar_end=NOW.replace(minute=15),
        action="enter_long",
    )

    assert result.outcome is ExecutionOutcome.BLOCKED
    assert broker.submit_count == 0
    assert len(store.load_all()) == 1


@pytest.mark.parametrize(
    "status",
    [PaperEnvironmentStatus.NOT_PAPER, PaperEnvironmentStatus.UNVERIFIABLE],
)
def test_unverified_environment_blocks_before_intent_and_submit(
    tmp_path: Path,
    status: PaperEnvironmentStatus,
) -> None:
    broker = ScenarioBroker(verification=status)
    execution, store, _ = service(broker, tmp_path)

    result = execute(execution)

    assert result.outcome is ExecutionOutcome.BLOCKED
    assert broker.submit_count == 0
    assert store.load_all() == ()


def test_dry_run_does_not_require_paper_proof_or_mutate(
    tmp_path: Path,
) -> None:
    broker = ScenarioBroker(verification=PaperEnvironmentStatus.UNVERIFIABLE)
    execution, store, _ = service(broker, tmp_path, dry_run=True)

    result = execute(execution)

    assert result.outcome is ExecutionOutcome.DRY_RUN
    assert broker.submit_count == 0
    assert store.load_all() == ()


def test_lifecycle_events_are_correlated_and_secret_free(
    tmp_path: Path,
) -> None:
    logger = MemoryLifecycleLogger()
    broker = ScenarioBroker(
        submitted=broker_order(
            BrokerOrderStatus.PARTIALLY_FILLED,
            filled_quantity=1,
        ),
        polls=[broker_order(BrokerOrderStatus.FILLED, filled_quantity=2)],
    )
    execution, _, _ = service(broker, tmp_path, logger=logger)

    execute(execution)

    event_types = {event.event_type for event in logger.events}
    assert {
        "order_intent_created",
        "order_submission_started",
        "order_submission_returned",
        "order_partial_fill",
        "order_filled",
        "position_generation_created",
        "position_quantity_changed",
    } <= event_types
    assert all(event.intent_id for event in logger.events)
    assert all(event.client_order_id for event in logger.events)
    assert "secret" not in repr(logger.events).lower()


def test_post_submission_order_persistence_failure_fails_closed(
    tmp_path: Path,
) -> None:
    broker = ScenarioBroker(
        submitted=broker_order(BrokerOrderStatus.FILLED, filled_quantity=2)
    )
    orders = FailOnceOrderStore(tmp_path / "orders.json", fail_on_save=3)
    positions = JsonPositionStateStore(tmp_path / "positions.json")
    broker.order_store = orders
    execution = PaperExecutionService(
        broker=broker,  # type: ignore[arg-type]
        settings=ExecutionSettings(dry_run=False),
        order_state_store=orders,
        position_state_store=positions,
        now=lambda: NOW,
    )

    result = execute(execution)

    assert result.outcome is ExecutionOutcome.RECONCILIATION_REQUIRED
    assert broker.submit_count == 1
    assert orders.load_all()[0].lifecycle_state is (
        OrderLifecycleState.RECONCILIATION_REQUIRED
    )
    assert positions.load("SPY").quantity == pytest.approx(2)


def test_position_persistence_failure_marks_intent_uncertain(
    tmp_path: Path,
) -> None:
    broker = ScenarioBroker(
        submitted=broker_order(BrokerOrderStatus.FILLED, filled_quantity=2)
    )
    orders = JsonOrderStateStore(tmp_path / "orders.json")
    positions = FailOncePositionStore(
        tmp_path / "positions.json",
        fail_on_save=2,
    )
    broker.order_store = orders
    execution = PaperExecutionService(
        broker=broker,  # type: ignore[arg-type]
        settings=ExecutionSettings(dry_run=False),
        order_state_store=orders,
        position_state_store=positions,
        now=lambda: NOW,
    )

    result = execute(execution)

    assert result.lifecycle_state == "reconciliation_required"
    assert broker.submit_count == 1
    assert orders.load_all()[0].last_error_type == (
        "position_persistence_failure"
    )


def test_logging_failure_does_not_rollback_durable_fill(
    tmp_path: Path,
) -> None:
    broker = ScenarioBroker(
        submitted=broker_order(BrokerOrderStatus.FILLED, filled_quantity=2)
    )
    execution, orders, positions = service(
        broker,
        tmp_path,
        logger=FailingLifecycleLogger(),
    )

    result = execute(execution)

    assert result.outcome is ExecutionOutcome.FILLED
    assert "lifecycle_log:OSError" in result.audit_logging_error
    assert orders.load_all()[0].lifecycle_state is OrderLifecycleState.FILLED
    assert positions.load("SPY").quantity == pytest.approx(2)


def test_broker_observations_cannot_regress_lifecycle_or_fill() -> None:
    accepted = OrderIntent(
        intent_id="intent-1",
        strategy_name="ema_9_21",
        symbol="SPY",
        timeframe_minutes=15,
        signal_bar_end=NOW,
        action="enter_long",
        side=OrderSide.BUY,
        requested_quantity=2,
        client_order_id="client-1",
        position_generation_id="pg-1",
        lifecycle_state=OrderLifecycleState.ACCEPTED,
        created_at=NOW,
        updated_at=NOW,
    )
    stale = advance_intent_from_broker_order(
        accepted,
        broker_order(
            BrokerOrderStatus.NEW,
            client_order_id="client-1",
        ),
        checked_at=NOW,
    )
    partial = advance_intent_from_broker_order(
        accepted,
        broker_order(
            BrokerOrderStatus.ACCEPTED,
            client_order_id="client-1",
            filled_quantity=1,
        ),
        checked_at=NOW,
    )
    backward = advance_intent_from_broker_order(
        partial,
        broker_order(
            BrokerOrderStatus.ACCEPTED,
            client_order_id="client-1",
            filled_quantity=0,
        ),
        checked_at=NOW,
    )

    assert stale.lifecycle_state is OrderLifecycleState.ACCEPTED
    assert partial.lifecycle_state is OrderLifecycleState.PARTIALLY_FILLED
    assert backward.lifecycle_state is OrderLifecycleState.RECONCILIATION_REQUIRED
