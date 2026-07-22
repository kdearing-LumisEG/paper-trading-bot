"""Tests for safe, idempotent paper execution."""

from collections import deque
from dataclasses import replace
from pathlib import Path

import pytest

from trading_bot.broker.models import (
    AccountSnapshot,
    BrokerOrder,
    BrokerOrderStatus,
    MarketOrderRequest,
    OrderSide,
    PaperEnvironmentStatus,
    PaperEnvironmentVerification,
    PositionSnapshot,
)
from trading_bot.execution.kill_switch import (
    StaticKillSwitch,
)
from trading_bot.execution.logging import (
    JsonlExecutionLogger,
)
from trading_bot.execution.models import (
    ExecutionOutcome,
    ExecutionSettings,
)
from trading_bot.execution.order_state import (
    JsonOrderStateStore,
)
from trading_bot.execution.position_state import (
    JsonPositionStateStore,
)
from trading_bot.execution.service import (
    PaperExecutionService,
)


class FakeBroker:
    def __init__(self) -> None:
        self.existing_order: BrokerOrder | None = None
        self.submitted_order = make_order(
            BrokerOrderStatus.NEW
        )
        self.poll_orders: deque[BrokerOrder] = deque()
        self.submit_count = 0
        self.lookup_count = 0
        self.cancelled_order_ids: list[str] = []
        self.last_request: MarketOrderRequest | None = None
        self.cancel_requested = False

    def verify_paper_environment(
        self,
    ) -> PaperEnvironmentVerification:
        return PaperEnvironmentVerification(
            status=PaperEnvironmentStatus.VERIFIED_PAPER,
            message="verified fake paper broker",
        )

    def submit_market_order(
        self,
        request: MarketOrderRequest,
    ) -> BrokerOrder:
        self.last_request = request
        self.submit_count += 1
        return replace(
            self.submitted_order,
            client_order_id=request.client_order_id,
            quantity=float(request.quantity),
            side=request.side,
        )

    def get_order(self, order_id: str) -> BrokerOrder:
        assert order_id == "order-1"
        if self.poll_orders:
            order = self.poll_orders.popleft()
        elif self.cancel_requested:
            order = make_order(BrokerOrderStatus.CANCELED)
        else:
            order = self.submitted_order
        if self.last_request is None:
            return order
        return replace(
            order,
            client_order_id=self.last_request.client_order_id,
            quantity=float(self.last_request.quantity),
            side=self.last_request.side,
        )

    def find_order_by_client_id(
        self,
        client_order_id: str,
    ) -> BrokerOrder | None:
        self.lookup_count += 1
        return self.existing_order

    def cancel_order(self, order_id: str) -> None:
        self.cancelled_order_ids.append(order_id)
        self.cancel_requested = True

    def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(
            account_id="account-1",
            cash=10000.0,
            buying_power=20000.0,
            equity=10000.0,
            trading_blocked=False,
            account_blocked=False,
        )

    def list_positions(self) -> list[PositionSnapshot]:
        return [
            PositionSnapshot(
                symbol="SPY",
                quantity=1.0,
                average_entry_price=500.0,
                market_value=501.0,
                unrealized_pnl=1.0,
            )
        ]


def make_order(
    status: BrokerOrderStatus,
) -> BrokerOrder:
    return BrokerOrder(
        order_id="order-1",
        client_order_id="signal-1",
        symbol="SPY",
        quantity=1.0,
        side=OrderSide.BUY,
        status=status,
        filled_quantity=(
            1.0
            if status is BrokerOrderStatus.FILLED
            else (
                0.5
                if status
                is BrokerOrderStatus.PARTIALLY_FILLED
                else 0.0
            )
        ),
        filled_average_price=(
            500.25
            if status is BrokerOrderStatus.FILLED
            or status
            is BrokerOrderStatus.PARTIALLY_FILLED
            else None
        ),
    )


def make_request() -> MarketOrderRequest:
    return MarketOrderRequest(
        symbol="SPY",
        quantity=1,
        side=OrderSide.BUY,
        client_order_id="signal-1",
    )


def make_service(
    broker: FakeBroker,
    *,
    dry_run: bool = False,
    max_poll_attempts: int = 3,
    kill_switch: StaticKillSwitch | None = None,
    logger: JsonlExecutionLogger | None = None,
    tmp_path: Path | None = None,
) -> PaperExecutionService:
    return PaperExecutionService(
        broker=broker,
        settings=ExecutionSettings(
            dry_run=dry_run,
            poll_interval_seconds=0.0,
            max_poll_attempts=max_poll_attempts,
            cancellation_confirmation_poll_seconds=0.01,
            cancellation_confirmation_timeout_seconds=0.01,
        ),
        kill_switch=kill_switch,
        logger=logger,
        sleeper=lambda _: None,
        order_state_store=(
            JsonOrderStateStore(
                tmp_path / "orders.json"
            )
            if tmp_path is not None
            else None
        ),
        position_state_store=(
            JsonPositionStateStore(
                tmp_path / "positions.json"
            )
            if tmp_path is not None
            else None
        ),
    )


def test_kill_switch_blocks_without_broker_calls() -> None:
    broker = FakeBroker()
    service = make_service(
        broker,
        kill_switch=StaticKillSwitch(active=True),
    )

    result = service.execute_market_order(
        make_request()
    )

    assert result.outcome is ExecutionOutcome.BLOCKED
    assert broker.lookup_count == 0
    assert broker.submit_count == 0


def test_duplicate_order_is_not_resubmitted() -> None:
    broker = FakeBroker()
    broker.existing_order = make_order(
        BrokerOrderStatus.ACCEPTED
    )

    result = make_service(
        broker
    ).execute_market_order(make_request())

    assert result.outcome is ExecutionOutcome.DUPLICATE
    assert result.order is broker.existing_order
    assert broker.submit_count == 0


def test_dry_run_checks_duplicate_but_does_not_submit() -> None:
    broker = FakeBroker()

    result = make_service(
        broker,
        dry_run=True,
    ).execute_market_order(make_request())

    assert result.outcome is ExecutionOutcome.DRY_RUN
    assert broker.lookup_count == 1
    assert broker.submit_count == 0


def test_order_is_polled_until_filled(tmp_path: Path) -> None:
    broker = FakeBroker()
    broker.poll_orders.extend(
        [
            make_order(
                BrokerOrderStatus.PARTIALLY_FILLED
            ),
            make_order(BrokerOrderStatus.FILLED),
        ]
    )

    result = make_service(
        broker,
        tmp_path=tmp_path,
    ).execute_market_order(make_request())

    assert result.outcome is ExecutionOutcome.FILLED
    assert result.poll_count == 2
    assert result.order is not None
    assert result.order.filled_average_price == pytest.approx(
        500.25
    )


def test_rejected_order_returns_terminal_result(
    tmp_path: Path,
) -> None:
    broker = FakeBroker()
    broker.submitted_order = make_order(
        BrokerOrderStatus.REJECTED
    )

    result = make_service(
        broker,
        tmp_path=tmp_path,
    ).execute_market_order(make_request())

    assert result.outcome is ExecutionOutcome.TERMINAL
    assert result.poll_count == 0
    assert "rejected" in result.message


def test_timeout_requests_cancellation(tmp_path: Path) -> None:
    broker = FakeBroker()

    result = make_service(
        broker,
        max_poll_attempts=2,
        tmp_path=tmp_path,
    ).execute_market_order(make_request())

    assert result.outcome is ExecutionOutcome.TERMINAL
    assert result.lifecycle_state == "canceled"
    assert result.poll_count == 3
    assert result.cancellation_requested is True
    assert broker.cancelled_order_ids == ["order-1"]


def test_account_and_positions_pass_through() -> None:
    service = make_service(FakeBroker())

    assert service.get_account().cash == pytest.approx(
        10000.0
    )
    assert service.list_positions()[0].symbol == "SPY"


def test_execution_result_is_logged(
    tmp_path: Path,
) -> None:
    path = tmp_path / "execution.jsonl"
    broker = FakeBroker()

    service = make_service(
        broker,
        dry_run=True,
        logger=JsonlExecutionLogger(path),
    )

    service.execute_market_order(make_request())

    contents = path.read_text(
        encoding="utf-8"
    )

    assert '"outcome": "dry_run"' in contents
    assert '"client_order_id": "signal-1"' in contents
