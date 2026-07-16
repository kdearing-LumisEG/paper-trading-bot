"""Alpaca paper-trading implementation of the broker interface."""

from __future__ import annotations

from typing import Any

from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import (
    OrderSide as AlpacaOrderSide,
)
from alpaca.trading.enums import TimeInForce
from alpaca.trading.requests import (
    MarketOrderRequest as AlpacaMarketOrderRequest,
)

from trading_bot.broker.models import (
    AccountSnapshot,
    BrokerOrder,
    BrokerOrderStatus,
    MarketOrderRequest,
    OrderSide,
    PositionSnapshot,
)


class AlpacaBrokerError(RuntimeError):
    """Raised when an Alpaca response cannot be normalized."""


def _enum_value(value: object) -> str:
    raw_value = getattr(value, "value", value)
    return str(raw_value).strip().lower()


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _required_float(
    value: object,
    field_name: str,
) -> float:
    if value is None or value == "":
        raise AlpacaBrokerError(
            f"Alpaca response is missing {field_name}."
        )
    return float(value)


def _normalized_status(
    value: object,
) -> BrokerOrderStatus:
    normalized = _enum_value(value)
    try:
        return BrokerOrderStatus(normalized)
    except ValueError:
        return BrokerOrderStatus.UNKNOWN


def _normalized_side(value: object) -> OrderSide:
    normalized = _enum_value(value)
    try:
        return OrderSide(normalized)
    except ValueError as exc:
        raise AlpacaBrokerError(
            f"Unsupported Alpaca order side: {normalized}"
        ) from exc


def _is_not_found(error: APIError) -> bool:
    if error.status_code == 404:
        return True

    try:
        message = error.message.lower()
    except (KeyError, ValueError):
        message = str(error).lower()

    return "not found" in message


class AlpacaPaperBroker:
    """Whole-share stock execution against Alpaca's paper endpoint."""

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        trading_client: TradingClient | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key cannot be empty.")
        if not secret_key.strip():
            raise ValueError("secret_key cannot be empty.")

        self._client = (
            trading_client
            if trading_client is not None
            else TradingClient(
                api_key=api_key,
                secret_key=secret_key,
                paper=True,
            )
        )

    @staticmethod
    def _to_order(order: Any) -> BrokerOrder:
        order_id = str(getattr(order, "id", ""))
        client_order_id = str(
            getattr(order, "client_order_id", "")
        )
        symbol = str(
            getattr(order, "symbol", "")
        ).upper()

        return BrokerOrder(
            order_id=order_id,
            client_order_id=client_order_id,
            symbol=symbol,
            quantity=_required_float(
                getattr(order, "qty", None),
                "qty",
            ),
            side=_normalized_side(
                getattr(order, "side", None)
            ),
            status=_normalized_status(
                getattr(order, "status", None)
            ),
            filled_quantity=float(
                getattr(order, "filled_qty", 0.0)
                or 0.0
            ),
            filled_average_price=_optional_float(
                getattr(
                    order,
                    "filled_avg_price",
                    None,
                )
            ),
            submitted_at=getattr(
                order,
                "submitted_at",
                None,
            ),
        )

    def submit_market_order(
        self,
        request: MarketOrderRequest,
    ) -> BrokerOrder:
        alpaca_side = (
            AlpacaOrderSide.BUY
            if request.side is OrderSide.BUY
            else AlpacaOrderSide.SELL
        )

        order_data = AlpacaMarketOrderRequest(
            symbol=request.symbol,
            qty=request.quantity,
            side=alpaca_side,
            time_in_force=TimeInForce.DAY,
            client_order_id=(
                request.client_order_id
            ),
        )

        order = self._client.submit_order(
            order_data=order_data
        )
        return self._to_order(order)

    def get_order(
        self,
        order_id: str,
    ) -> BrokerOrder:
        order = self._client.get_order_by_id(
            order_id
        )
        return self._to_order(order)

    def find_order_by_client_id(
        self,
        client_order_id: str,
    ) -> BrokerOrder | None:
        try:
            order = self._client.get_order_by_client_id(
                client_order_id
            )
        except APIError as exc:
            if _is_not_found(exc):
                return None
            raise

        return self._to_order(order)

    def cancel_order(
        self,
        order_id: str,
    ) -> None:
        self._client.cancel_order_by_id(order_id)

    def get_account(self) -> AccountSnapshot:
        account = self._client.get_account()

        return AccountSnapshot(
            account_id=str(account.id),
            cash=_required_float(
                account.cash,
                "cash",
            ),
            buying_power=_required_float(
                account.buying_power,
                "buying_power",
            ),
            equity=_required_float(
                account.equity,
                "equity",
            ),
            trading_blocked=bool(
                account.trading_blocked
            ),
            account_blocked=bool(
                account.account_blocked
            ),
        )

    def list_positions(
        self,
    ) -> list[PositionSnapshot]:
        positions = self._client.get_all_positions()

        return [
            PositionSnapshot(
                symbol=str(position.symbol).upper(),
                quantity=_required_float(
                    position.qty,
                    "position qty",
                ),
                average_entry_price=(
                    _required_float(
                        position.avg_entry_price,
                        "average entry price",
                    )
                ),
                market_value=_required_float(
                    position.market_value,
                    "market value",
                ),
                unrealized_pnl=_required_float(
                    position.unrealized_pl,
                    "unrealized P&L",
                ),
            )
            for position in positions
        ]
