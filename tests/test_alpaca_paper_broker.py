"""Tests for Alpaca response and request normalization."""

from datetime import datetime, timezone
from types import SimpleNamespace

from alpaca.trading.enums import OrderSide as AlpacaOrderSide
from alpaca.trading.enums import TimeInForce
import pytest

from trading_bot.broker.alpaca_client import (
    AlpacaPaperBroker,
)
from trading_bot.broker.models import (
    BrokerOrderStatus,
    MarketOrderRequest,
    OrderSide,
)


class FakeTradingClient:
    def __init__(self) -> None:
        self.submitted_order_data = None
        self.cancelled_order_id = None

    @staticmethod
    def order(
        status: str = "new",
    ) -> SimpleNamespace:
        return SimpleNamespace(
            id="broker-order-1",
            client_order_id="signal-1",
            symbol="SPY",
            qty="2",
            side=AlpacaOrderSide.BUY,
            status=SimpleNamespace(value=status),
            filled_qty="0",
            filled_avg_price=None,
            submitted_at=datetime(
                2026,
                1,
                2,
                tzinfo=timezone.utc,
            ),
        )

    def submit_order(self, order_data):
        self.submitted_order_data = order_data
        return self.order()

    def get_order_by_id(self, order_id: str):
        assert order_id == "broker-order-1"
        return self.order(status="filled")

    def get_order_by_client_id(
        self,
        client_order_id: str,
    ):
        assert client_order_id == "signal-1"
        return self.order()

    def cancel_order_by_id(self, order_id: str):
        self.cancelled_order_id = order_id

    def get_account(self):
        return SimpleNamespace(
            id="account-1",
            cash="10000.25",
            buying_power="20000.50",
            equity="10500.75",
            trading_blocked=False,
            account_blocked=False,
        )

    def get_all_positions(self):
        return [
            SimpleNamespace(
                symbol="SPY",
                qty="2",
                avg_entry_price="500.25",
                market_value="1010.00",
                unrealized_pl="9.50",
            )
        ]


def make_broker(
    client: FakeTradingClient,
) -> AlpacaPaperBroker:
    return AlpacaPaperBroker(
        api_key="paper-key",
        secret_key="paper-secret",
        trading_client=client,  # type: ignore[arg-type]
    )


def test_submit_market_order_uses_alpaca_request() -> None:
    client = FakeTradingClient()
    broker = make_broker(client)

    order = broker.submit_market_order(
        MarketOrderRequest(
            symbol="SPY",
            quantity=2,
            side=OrderSide.BUY,
            client_order_id="signal-1",
        )
    )

    request = client.submitted_order_data

    assert request.symbol == "SPY"
    assert request.qty == 2
    assert request.side is AlpacaOrderSide.BUY
    assert request.time_in_force is TimeInForce.DAY
    assert request.client_order_id == "signal-1"
    assert order.status is BrokerOrderStatus.NEW


def test_account_and_position_are_normalized() -> None:
    broker = make_broker(FakeTradingClient())

    account = broker.get_account()
    positions = broker.list_positions()

    assert account.cash == pytest.approx(10000.25)
    assert account.buying_power == pytest.approx(20000.50)
    assert len(positions) == 1
    assert positions[0].quantity == pytest.approx(2.0)
    assert positions[0].unrealized_pnl == pytest.approx(9.50)


def test_get_and_cancel_order_delegate_to_client() -> None:
    client = FakeTradingClient()
    broker = make_broker(client)

    order = broker.get_order("broker-order-1")
    broker.cancel_order("broker-order-1")

    assert order.status is BrokerOrderStatus.FILLED
    assert client.cancelled_order_id == "broker-order-1"
