"""Tests for Alpaca open-order retrieval."""

from types import SimpleNamespace

from alpaca.trading.enums import (
    OrderSide as AlpacaOrderSide,
)
from alpaca.trading.enums import QueryOrderStatus

from trading_bot.broker.alpaca_client import (
    AlpacaPaperBroker,
)
from trading_bot.broker.models import (
    BrokerOrderStatus,
)


class FakeTradingClient:
    def __init__(self) -> None:
        self.request = None

    def get_orders(self, request):
        self.request = request

        return [
            SimpleNamespace(
                id="order-1",
                client_order_id="signal-1",
                symbol="SPY",
                qty="1",
                side=AlpacaOrderSide.BUY,
                status=SimpleNamespace(
                    value="accepted"
                ),
                filled_qty="0",
                filled_avg_price=None,
                submitted_at=None,
            )
        ]


def test_open_orders_use_open_filter() -> None:
    client = FakeTradingClient()

    broker = AlpacaPaperBroker(
        api_key="paper-key",
        secret_key="paper-secret",
        trading_client=client,  # type: ignore[arg-type]
    )

    orders = broker.list_open_orders()

    assert client.request.status is (
        QueryOrderStatus.OPEN
    )
    assert client.request.limit == 500
    assert len(orders) == 1
    assert orders[0].status is (
        BrokerOrderStatus.ACCEPTED
    )
