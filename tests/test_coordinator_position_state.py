"""Tests for coordinator updates to tracked position state."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from trading_bot.backtest.risk_manager import (
    RiskManager,
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
    SignalExecutionCoordinator,
)
from trading_bot.execution.models import (
    ExecutionOutcome,
    ExecutionResult,
)
from trading_bot.execution.position_state import (
    JsonPositionStateStore,
    TrackedPosition,
)
from trading_bot.execution.signal_models import (
    StrategySignal,
    StrategySignalEvent,
)


class FakeExecutionService:
    def __init__(self) -> None:
        self.positions: list[
            PositionSnapshot
        ] = []
        self.fill_price = 500.25
        self.position_store: JsonPositionStateStore | None = None

    def list_positions(
        self,
    ) -> list[PositionSnapshot]:
        return list(self.positions)

    def get_account(
        self,
    ) -> AccountSnapshot:
        return AccountSnapshot(
            account_id="account-1",
            cash=10_000.0,
            buying_power=20_000.0,
            equity=10_000.0,
            trading_blocked=False,
            account_blocked=False,
        )

    def execute_market_order(
        self,
        request: MarketOrderRequest,
        **kwargs,
    ) -> ExecutionResult:
        assert self.position_store is not None
        generation = kwargs["position_generation_id"]
        if request.side is OrderSide.BUY:
            self.position_store.save(
                TrackedPosition(
                    symbol=request.symbol,
                    quantity=float(request.quantity),
                    average_entry_price=self.fill_price,
                    updated_at=datetime(
                        2026,
                        1,
                        2,
                        15,
                        1,
                        tzinfo=timezone.utc,
                    ),
                    strategy_name=kwargs["strategy_name"],
                    position_generation_id=generation,
                    entry_client_order_id=(
                        request.client_order_id
                    ),
                    entry_broker_order_id="order-1",
                )
            )
        else:
            current = self.position_store.load(request.symbol)
            assert current is not None
            self.position_store.save(
                TrackedPosition.flat(
                    symbol=request.symbol,
                    updated_at=datetime(
                        2026,
                        1,
                        2,
                        15,
                        1,
                        tzinfo=timezone.utc,
                    ),
                    strategy_name=current.strategy_name,
                    position_generation_id=generation,
                    entry_intent_id=current.entry_intent_id,
                    entry_client_order_id=(
                        current.entry_client_order_id
                    ),
                    entry_broker_order_id=(
                        current.entry_broker_order_id
                    ),
                    exit_client_order_id=(
                        request.client_order_id
                    ),
                    exit_broker_order_id="order-1",
                )
            )
        return ExecutionResult(
            request=request,
            outcome=ExecutionOutcome.FILLED,
            message="filled",
            order=BrokerOrder(
                order_id="order-1",
                client_order_id=(
                    request.client_order_id
                ),
                symbol=request.symbol,
                quantity=float(
                    request.quantity
                ),
                side=request.side,
                status=BrokerOrderStatus.FILLED,
                filled_quantity=float(
                    request.quantity
                ),
                filled_average_price=(
                    self.fill_price
                ),
                submitted_at=datetime(
                    2026,
                    1,
                    2,
                    15,
                    1,
                    tzinfo=timezone.utc,
                ),
            ),
            newly_filled_quantity=float(
                request.quantity
            ),
        )


def event(
    signal: StrategySignal,
) -> StrategySignalEvent:
    return StrategySignalEvent(
        strategy_name="ema_9_21",
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
        reference_price=500.0,
    )


def test_filled_entry_tracks_position(
    tmp_path: Path,
) -> None:
    path = tmp_path / "position.json"
    service = FakeExecutionService()
    service.position_store = JsonPositionStateStore(path)

    coordinator = SignalExecutionCoordinator(
        execution_service=service,  # type: ignore[arg-type]
        risk_manager=RiskManager(),
        position_state_store=(
            JsonPositionStateStore(path)
        ),
    )

    coordinator.handle(
        event(
            StrategySignal.ENTER_LONG
        )
    )

    tracked = JsonPositionStateStore(
        path
    ).load("SPY")

    assert tracked is not None
    assert tracked.quantity == pytest.approx(2.0)
    assert tracked.average_entry_price == pytest.approx(
        500.25
    )


def test_filled_exit_tracks_flat_state(
    tmp_path: Path,
) -> None:
    path = tmp_path / "position.json"
    service = FakeExecutionService()
    service.positions = [
        PositionSnapshot(
            symbol="SPY",
            quantity=2.0,
            average_entry_price=490.0,
            market_value=1000.0,
            unrealized_pnl=20.0,
        )
    ]
    service.fill_price = 500.0
    store = JsonPositionStateStore(path)
    store.save(
        TrackedPosition(
            symbol="SPY",
            quantity=2.0,
            average_entry_price=490.0,
            updated_at=datetime(
                2026,
                1,
                2,
                14,
                30,
                tzinfo=timezone.utc,
            ),
            strategy_name="ema_9_21",
            position_generation_id="pg-existing",
            entry_intent_id="entry-intent",
            entry_client_order_id="entry-client",
            entry_broker_order_id="entry-order",
        )
    )
    service.position_store = store

    coordinator = SignalExecutionCoordinator(
        execution_service=service,  # type: ignore[arg-type]
        risk_manager=RiskManager(),
        position_state_store=(
            JsonPositionStateStore(path)
        ),
    )

    result = coordinator.handle(
        event(
            StrategySignal.EXIT_LONG
        )
    )

    tracked = JsonPositionStateStore(
        path
    ).load("SPY")

    assert tracked is not None
    assert tracked.quantity == pytest.approx(0.0)
    assert tracked.average_entry_price is None
    assert result.realized_net_pnl_recorded == pytest.approx(
        20.0
    )
