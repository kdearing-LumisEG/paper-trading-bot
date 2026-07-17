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
    ) -> ExecutionResult:
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
    )


def test_filled_entry_tracks_position(
    tmp_path: Path,
) -> None:
    path = tmp_path / "position.json"
    service = FakeExecutionService()

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
