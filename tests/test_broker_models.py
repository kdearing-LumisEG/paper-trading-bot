"""Tests for broker-neutral request and order models."""

import pytest

from trading_bot.broker.models import (
    BrokerModelError,
    BrokerOrderStatus,
    MarketOrderRequest,
    OrderSide,
)


def test_market_order_normalizes_symbol() -> None:
    request = MarketOrderRequest(
        symbol=" spy ",
        quantity=1,
        side=OrderSide.BUY,
        client_order_id="ema-20260102-143000",
    )

    assert request.symbol == "SPY"


@pytest.mark.parametrize("quantity", [0, -1, True, 1.5])
def test_invalid_quantity_fails(
    quantity: object,
) -> None:
    with pytest.raises(
        BrokerModelError,
        match="positive integer",
    ):
        MarketOrderRequest(
            symbol="SPY",
            quantity=quantity,  # type: ignore[arg-type]
            side=OrderSide.BUY,
            client_order_id="valid-id",
        )


def test_invalid_client_order_id_fails() -> None:
    with pytest.raises(
        BrokerModelError,
        match="unsupported characters",
    ):
        MarketOrderRequest(
            symbol="SPY",
            quantity=1,
            side=OrderSide.BUY,
            client_order_id="contains spaces",
        )


def test_terminal_statuses_are_identified() -> None:
    assert BrokerOrderStatus.FILLED.is_terminal
    assert BrokerOrderStatus.REJECTED.is_terminal
    assert not BrokerOrderStatus.NEW.is_terminal
    assert not BrokerOrderStatus.PARTIALLY_FILLED.is_terminal
