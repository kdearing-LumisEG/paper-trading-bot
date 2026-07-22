"""Tests for signal-to-order coordination."""

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from trading_bot.backtest.risk_controls import (
    MaxTradesPerSession,
)
from trading_bot.backtest.risk_manager import (
    RiskManager,
    SessionRiskConfig,
)
from trading_bot.broker.models import (
    AccountSnapshot,
    BrokerOrder,
    BrokerOrderStatus,
    MarketOrderRequest,
    OrderSide,
    PositionSnapshot,
)
from trading_bot.execution.coordinator import (
    ACCOUNT_BLOCKED_REASON,
    ALREADY_FLAT_REASON,
    ALREADY_LONG_REASON,
    FRACTIONAL_POSITION_REASON,
    BUYING_POWER_REASON,
    KILL_SWITCH_REASON,
    REFERENCE_PRICE_REASON,
    SignalExecutionCoordinator,
)
from trading_bot.execution.decision_logging import (
    JsonlSignalDecisionLogger,
)
from trading_bot.execution.models import (
    ExecutionOutcome,
    ExecutionResult,
)
from trading_bot.execution.position_state import (
    TrackedPosition,
)
from trading_bot.execution.signal_models import (
    SignalHandlingOutcome,
    StrategySignal,
    StrategySignalEvent,
)


class FakeExecutionService:
    def __init__(
        self,
    ) -> None:
        self.positions: list[
            PositionSnapshot
        ] = []

        self.account = AccountSnapshot(
            account_id="account-1",
            cash=10_000.0,
            buying_power=20_000.0,
            equity=10_000.0,
            trading_blocked=False,
            account_blocked=False,
        )

        self.execution_outcome = (
            ExecutionOutcome.DRY_RUN
        )

        self.fill_price = 105.0
        self.requests: list[
            MarketOrderRequest
        ] = []
        self.position_calls = 0
        self.account_calls = 0

    def list_positions(
        self,
    ) -> list[PositionSnapshot]:
        self.position_calls += 1
        return list(self.positions)

    def get_account(
        self,
    ) -> AccountSnapshot:
        self.account_calls += 1
        return self.account

    def execute_market_order(
        self,
        request: MarketOrderRequest,
        **kwargs,
    ) -> ExecutionResult:
        del kwargs
        self.requests.append(request)

        order = None

        if self.execution_outcome in {
            ExecutionOutcome.FILLED,
            ExecutionOutcome.DUPLICATE,
        }:
            order = BrokerOrder(
                order_id="order-1",
                client_order_id=(
                    request.client_order_id
                ),
                symbol=request.symbol,
                quantity=float(
                    request.quantity
                ),
                side=request.side,
                status=(
                    BrokerOrderStatus.FILLED
                    if self.execution_outcome
                    is ExecutionOutcome.FILLED
                    else BrokerOrderStatus.ACCEPTED
                ),
                filled_quantity=(
                    float(request.quantity)
                    if self.execution_outcome
                    is ExecutionOutcome.FILLED
                    else 0.0
                ),
                filled_average_price=(
                    self.fill_price
                    if self.execution_outcome
                    is ExecutionOutcome.FILLED
                    else None
                ),
            )

        return ExecutionResult(
            request=request,
            outcome=self.execution_outcome,
            message="fake execution result",
            order=order,
            newly_filled_quantity=(
                float(request.quantity)
                if self.execution_outcome
                is ExecutionOutcome.FILLED
                else 0.0
            ),
        )


class MemoryPositionStateStore:
    def __init__(
        self,
        position: TrackedPosition | None = None,
    ) -> None:
        self.position = position

    def load(self, symbol: str) -> TrackedPosition | None:
        del symbol
        return self.position

    def save(self, position: TrackedPosition) -> None:
        self.position = position


class RecordingRiskStore:
    def __init__(
        self,
    ) -> None:
        self.save_count = 0

    def save(
        self,
        manager: RiskManager,
    ) -> None:
        del manager
        self.save_count += 1


def make_event(
    signal: StrategySignal,
) -> StrategySignalEvent:
    return StrategySignalEvent(
        strategy_name="ema_crossover_9_21",
        symbol="SPY",
        signal=signal,
        signal_time=datetime(
            2026,
            1,
            2,
            15,
            0,
            tzinfo=timezone.utc,
        ),
        entry_quantity=2,
        timeframe_minutes=15,
        reference_price=100.0,
    )


def make_position(
    quantity: float = 2.0,
    average_entry_price: float = 100.0,
) -> PositionSnapshot:
    return PositionSnapshot(
        symbol="SPY",
        quantity=quantity,
        average_entry_price=(
            average_entry_price
        ),
        market_value=(
            quantity
            * average_entry_price
        ),
        unrealized_pnl=0.0,
    )


def make_coordinator(
    service: FakeExecutionService,
    manager: RiskManager | None = None,
    store: RecordingRiskStore | None = None,
    logger=None,
) -> SignalExecutionCoordinator:
    tracked_position = (
        TrackedPosition(
            symbol="SPY",
            quantity=service.positions[0].quantity,
            average_entry_price=(
                service.positions[0].average_entry_price
            ),
            updated_at=datetime(
                2026,
                1,
                2,
                14,
                30,
                tzinfo=timezone.utc,
            ),
            strategy_name="ema_crossover_9_21",
            position_generation_id="pg-test",
        )
        if service.positions
        else None
    )
    return SignalExecutionCoordinator(
        execution_service=service,  # type: ignore[arg-type]
        risk_manager=(
            manager
            if manager is not None
            else RiskManager()
        ),
        risk_state_store=store,  # type: ignore[arg-type]
        position_state_store=(
            MemoryPositionStateStore(
                tracked_position
            )
        ),
        logger=logger,
    )


def test_hold_signal_makes_no_broker_calls() -> None:
    service = FakeExecutionService()

    result = make_coordinator(
        service
    ).handle(
        make_event(
            StrategySignal.HOLD
        )
    )

    assert result.outcome is (
        SignalHandlingOutcome.NO_ACTION
    )
    assert service.position_calls == 0
    assert service.account_calls == 0
    assert service.requests == []


def test_entry_while_long_is_ignored() -> None:
    service = FakeExecutionService()
    service.positions = [
        make_position()
    ]

    result = make_coordinator(
        service
    ).handle(
        make_event(
            StrategySignal.ENTER_LONG
        )
    )

    assert result.reason == (
        ALREADY_LONG_REASON
    )
    assert service.requests == []


def test_exit_while_flat_is_ignored() -> None:
    service = FakeExecutionService()

    result = make_coordinator(
        service
    ).handle(
        make_event(
            StrategySignal.EXIT_LONG
        )
    )

    assert result.reason == (
        ALREADY_FLAT_REASON
    )
    assert service.requests == []


def test_account_block_blocks_order() -> None:
    service = FakeExecutionService()

    service.account = AccountSnapshot(
        account_id="account-1",
        cash=10_000.0,
        buying_power=20_000.0,
        equity=10_000.0,
        trading_blocked=False,
        account_blocked=True,
    )

    result = make_coordinator(
        service
    ).handle(
        make_event(
            StrategySignal.ENTER_LONG
        )
    )

    assert result.outcome is (
        SignalHandlingOutcome.BLOCKED
    )
    assert result.reason == (
        ACCOUNT_BLOCKED_REASON
    )
    assert service.requests == []


def test_risk_limit_blocks_entry() -> None:
    service = FakeExecutionService()

    manager = RiskManager(
        SessionRiskConfig(
            max_trades_per_session=(
                MaxTradesPerSession(1)
            )
        )
    )

    manager.record_entry(
        "2026-01-02T14:45:00Z"
    )

    result = make_coordinator(
        service,
        manager=manager,
    ).handle(
        make_event(
            StrategySignal.ENTER_LONG
        )
    )

    assert result.outcome is (
        SignalHandlingOutcome.BLOCKED
    )
    assert result.reason == (
        "max_trades_per_session"
    )
    assert service.requests == []


@pytest.mark.parametrize("buying_power", [199.99, float("nan")])
def test_entry_requires_sufficient_known_buying_power(
    buying_power: float,
) -> None:
    service = FakeExecutionService()
    service.account = replace(
        service.account,
        buying_power=buying_power,
    )

    result = make_coordinator(service).handle(
        make_event(StrategySignal.ENTER_LONG)
    )

    assert result.outcome is SignalHandlingOutcome.BLOCKED
    assert result.reason == BUYING_POWER_REASON
    assert service.requests == []


def test_entry_requires_reference_price() -> None:
    service = FakeExecutionService()
    event = replace(
        make_event(StrategySignal.ENTER_LONG),
        reference_price=None,
    )

    result = make_coordinator(service).handle(event)

    assert result.reason == REFERENCE_PRICE_REASON
    assert service.requests == []


def test_exit_bypasses_buying_power_gate() -> None:
    service = FakeExecutionService()
    service.positions = [make_position()]
    service.account = replace(service.account, buying_power=0.0)

    result = make_coordinator(service).handle(
        make_event(StrategySignal.EXIT_LONG)
    )

    assert result.outcome is SignalHandlingOutcome.ORDER_ATTEMPTED
    assert service.requests[0].side is OrderSide.SELL


def test_dry_run_does_not_mutate_risk_state() -> None:
    service = FakeExecutionService()
    manager = RiskManager()
    store = RecordingRiskStore()

    result = make_coordinator(
        service,
        manager=manager,
        store=store,
    ).handle(
        make_event(
            StrategySignal.ENTER_LONG
        )
    )

    assert result.execution_result is not None
    assert result.execution_result.outcome is (
        ExecutionOutcome.DRY_RUN
    )

    snapshot = manager.snapshot(
        "2026-01-02T15:00:00Z"
    )

    assert snapshot.trades_started == 0
    assert store.save_count == 0


def test_filled_entry_records_session_trade() -> None:
    service = FakeExecutionService()

    service.execution_outcome = (
        ExecutionOutcome.FILLED
    )

    manager = RiskManager()
    store = RecordingRiskStore()

    result = make_coordinator(
        service,
        manager=manager,
        store=store,
    ).handle(
        make_event(
            StrategySignal.ENTER_LONG
        )
    )

    assert result.outcome is (
        SignalHandlingOutcome.ORDER_ATTEMPTED
    )

    assert manager.snapshot(
        "2026-01-02T15:00:00Z"
    ).trades_started == 1

    assert store.save_count == 1


def test_exit_closes_full_whole_position() -> None:
    service = FakeExecutionService()
    service.positions = [
        make_position(quantity=3.0)
    ]

    make_coordinator(
        service
    ).handle(
        make_event(
            StrategySignal.EXIT_LONG
        )
    )

    request = service.requests[0]

    assert request.side is OrderSide.SELL
    assert request.quantity == 3


def test_fractional_position_blocks_exit() -> None:
    service = FakeExecutionService()
    service.positions = [
        make_position(quantity=1.5)
    ]

    result = make_coordinator(
        service
    ).handle(
        make_event(
            StrategySignal.EXIT_LONG
        )
    )

    assert result.outcome is (
        SignalHandlingOutcome.BLOCKED
    )
    assert result.reason == (
        FRACTIONAL_POSITION_REASON
    )
    assert service.requests == []


def test_filled_exit_records_realized_pnl() -> None:
    service = FakeExecutionService()
    service.positions = [
        make_position(
            quantity=2.0,
            average_entry_price=100.0,
        )
    ]

    service.execution_outcome = (
        ExecutionOutcome.FILLED
    )
    service.fill_price = 105.0

    manager = RiskManager()
    store = RecordingRiskStore()

    result = make_coordinator(
        service,
        manager=manager,
        store=store,
    ).handle(
        make_event(
            StrategySignal.EXIT_LONG
        )
    )

    assert (
        result.realized_net_pnl_recorded
        == pytest.approx(10.0)
    )

    snapshot = manager.snapshot(
        "2026-01-02T15:00:00Z"
    )

    assert snapshot.realized_net_pnl == (
        pytest.approx(10.0)
    )

    assert store.save_count == 1


def test_client_order_id_is_stable() -> None:
    first_service = FakeExecutionService()
    second_service = FakeExecutionService()

    event = make_event(
        StrategySignal.ENTER_LONG
    )

    make_coordinator(
        first_service
    ).handle(event)

    make_coordinator(
        second_service
    ).handle(event)

    assert (
        first_service.requests[
            0
        ].client_order_id
        == second_service.requests[
            0
        ].client_order_id
    )


def test_kill_switch_result_is_propagated() -> None:
    service = FakeExecutionService()

    service.execution_outcome = (
        ExecutionOutcome.BLOCKED
    )

    result = make_coordinator(
        service
    ).handle(
        make_event(
            StrategySignal.ENTER_LONG
        )
    )

    assert result.outcome is (
        SignalHandlingOutcome.BLOCKED
    )
    assert result.reason == (
        KILL_SWITCH_REASON
    )


def test_signal_decision_is_logged(
    tmp_path: Path,
) -> None:
    path = tmp_path / "decisions.jsonl"

    service = FakeExecutionService()

    coordinator = make_coordinator(
        service,
        logger=JsonlSignalDecisionLogger(
            path
        ),
    )

    coordinator.handle(
        make_event(
            StrategySignal.HOLD
        )
    )

    contents = path.read_text(
        encoding="utf-8"
    )

    assert '"signal": "hold"' in contents
    assert '"outcome": "no_action"' in contents
