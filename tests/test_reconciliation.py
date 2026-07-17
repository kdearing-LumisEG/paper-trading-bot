"""Tests for broker-versus-local operational reconciliation."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from trading_bot.broker.models import (
    AccountSnapshot,
    BrokerOrder,
    BrokerOrderStatus,
    OrderSide,
    PositionSnapshot,
)
from trading_bot.execution.position_state import (
    JsonPositionStateStore,
    TrackedPosition,
)
from trading_bot.runtime.reconciliation import (
    ReconciliationIssueCode,
    ReconciliationService,
)


class FakeExecutionService:
    def __init__(self) -> None:
        self.account = AccountSnapshot(
            account_id="account-1",
            cash=10_000.0,
            buying_power=20_000.0,
            equity=10_000.0,
            trading_blocked=False,
            account_blocked=False,
        )
        self.positions: list[
            PositionSnapshot
        ] = []
        self.open_orders: list[
            BrokerOrder
        ] = []

    def get_account(
        self,
    ) -> AccountSnapshot:
        return self.account

    def list_positions(
        self,
    ) -> list[PositionSnapshot]:
        return list(self.positions)

    def list_open_orders(
        self,
    ) -> list[BrokerOrder]:
        return list(self.open_orders)


def position(
    *,
    symbol: str = "SPY",
    quantity: float = 1.0,
    average_entry_price: float = 500.0,
) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=symbol,
        quantity=quantity,
        average_entry_price=average_entry_price,
        market_value=(
            quantity * average_entry_price
        ),
        unrealized_pnl=0.0,
    )


def open_order(
    *,
    symbol: str = "SPY",
) -> BrokerOrder:
    return BrokerOrder(
        order_id="order-1",
        client_order_id="signal-1",
        symbol=symbol,
        quantity=1.0,
        side=OrderSide.BUY,
        status=BrokerOrderStatus.ACCEPTED,
    )


def reconciler(
    *,
    service: FakeExecutionService,
    path: Path,
) -> ReconciliationService:
    return ReconciliationService(
        execution_service=service,  # type: ignore[arg-type]
        position_state_store=(
            JsonPositionStateStore(path)
        ),
        symbol="SPY",
        average_price_tolerance=0.01,
        now=lambda: datetime(
            2026,
            1,
            2,
            15,
            0,
            tzinfo=timezone.utc,
        ),
    )


def test_flat_broker_without_local_state_is_safe(
    tmp_path: Path,
) -> None:
    report = reconciler(
        service=FakeExecutionService(),
        path=tmp_path / "position.json",
    ).run()

    assert report.safe
    assert report.issues == []


def test_open_order_fails_closed(
    tmp_path: Path,
) -> None:
    service = FakeExecutionService()
    service.open_orders = [
        open_order()
    ]

    report = reconciler(
        service=service,
        path=tmp_path / "position.json",
    ).run()

    assert not report.safe
    assert (
        ReconciliationIssueCode.OPEN_ORDER.value
        in report.issue_codes
    )


def test_untracked_broker_position_fails_closed(
    tmp_path: Path,
) -> None:
    service = FakeExecutionService()
    service.positions = [
        position()
    ]

    report = reconciler(
        service=service,
        path=tmp_path / "position.json",
    ).run()

    assert not report.safe
    assert (
        ReconciliationIssueCode
        .UNTRACKED_POSITION.value
        in report.issue_codes
    )


def test_matching_tracked_position_is_safe(
    tmp_path: Path,
) -> None:
    path = tmp_path / "position.json"
    store = JsonPositionStateStore(path)

    store.save(
        TrackedPosition(
            symbol="SPY",
            quantity=1.0,
            average_entry_price=500.0,
            updated_at=datetime.now(
                timezone.utc
            ),
        )
    )

    service = FakeExecutionService()
    service.positions = [
        position()
    ]

    report = reconciler(
        service=service,
        path=path,
    ).run()

    assert report.safe


def test_quantity_mismatch_fails_closed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "position.json"

    JsonPositionStateStore(path).save(
        TrackedPosition(
            symbol="SPY",
            quantity=1.0,
            average_entry_price=500.0,
            updated_at=datetime.now(
                timezone.utc
            ),
        )
    )

    service = FakeExecutionService()
    service.positions = [
        position(quantity=2.0)
    ]

    report = reconciler(
        service=service,
        path=path,
    ).run()

    assert not report.safe
    assert (
        ReconciliationIssueCode
        .POSITION_QUANTITY_MISMATCH.value
        in report.issue_codes
    )


def test_unexpected_symbol_position_fails_closed(
    tmp_path: Path,
) -> None:
    service = FakeExecutionService()
    service.positions = [
        position(symbol="QQQ")
    ]

    report = reconciler(
        service=service,
        path=tmp_path / "position.json",
    ).run()

    assert not report.safe
    assert (
        ReconciliationIssueCode
        .UNEXPECTED_POSITION.value
        in report.issue_codes
    )


def test_explicit_adoption_tracks_safe_position(
    tmp_path: Path,
) -> None:
    path = tmp_path / "position.json"
    service = FakeExecutionService()
    service.positions = [
        position(
            quantity=2.0,
            average_entry_price=501.25,
        )
    ]

    report = reconciler(
        service=service,
        path=path,
    ).run(
        adopt_position=True
    )

    assert report.safe
    assert report.adopted

    tracked = JsonPositionStateStore(
        path
    ).load("SPY")

    assert tracked is not None
    assert tracked.adopted
    assert tracked.quantity == pytest.approx(2.0)
    assert tracked.average_entry_price == pytest.approx(
        501.25
    )


def test_adoption_is_blocked_while_order_is_open(
    tmp_path: Path,
) -> None:
    service = FakeExecutionService()
    service.positions = [
        position()
    ]
    service.open_orders = [
        open_order()
    ]

    report = reconciler(
        service=service,
        path=tmp_path / "position.json",
    ).run(
        adopt_position=True
    )

    assert not report.safe
    assert not report.adopted
    assert (
        ReconciliationIssueCode
        .ADOPTION_NOT_ALLOWED.value
        in report.issue_codes
    )
