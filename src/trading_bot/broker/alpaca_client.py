"""Alpaca paper-trading implementation of the broker interface."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import (
    OrderSide as AlpacaOrderSide,
)
from alpaca.trading.enums import QueryOrderStatus
from alpaca.trading.enums import TimeInForce
from alpaca.trading.requests import (
    GetOrdersRequest,
    MarketOrderRequest as AlpacaMarketOrderRequest,
)

from trading_bot.broker.models import (
    AccountSnapshot,
    BrokerErrorKind,
    BrokerExecutionError,
    BrokerOrder,
    BrokerOrderStatus,
    MarketClockSnapshot,
    MarketOrderRequest,
    OrderSide,
    PaperEnvironmentStatus,
    PaperEnvironmentVerification,
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



def _required_datetime(
    value: object,
    field_name: str,
) -> datetime:
    if not isinstance(value, datetime):
        raise AlpacaBrokerError(
            f"Alpaca response is missing {field_name}."
        )

    if value.tzinfo is None:
        return value.replace(
            tzinfo=timezone.utc
        )

    return value.astimezone(
        timezone.utc
    )


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


def _paper_environment_evidence(
    client: object,
) -> PaperEnvironmentVerification:
    """Isolate SDK endpoint inspection behind one tested boundary."""

    sandbox = getattr(client, "_sandbox", None)
    raw_base_url = getattr(client, "_base_url", None)
    base_url = str(
        getattr(raw_base_url, "value", raw_base_url)
        or ""
    ).rstrip("/").lower()
    expected = "https://paper-api.alpaca.markets"

    if sandbox is True and base_url == expected:
        return PaperEnvironmentVerification(
            status=PaperEnvironmentStatus.VERIFIED_PAPER,
            message=(
                "Alpaca client sandbox mode and paper endpoint "
                "were both verified."
            ),
        )

    if sandbox is False or (
        base_url
        and base_url != expected
    ):
        return PaperEnvironmentVerification(
            status=PaperEnvironmentStatus.NOT_PAPER,
            message=(
                "Alpaca client evidence does not identify the "
                "paper endpoint."
            ),
        )

    return PaperEnvironmentVerification(
        status=PaperEnvironmentStatus.UNVERIFIABLE,
        message=(
            "Alpaca client does not expose sufficient paper "
            "environment evidence."
        ),
    )


def _broker_error(
    error: Exception,
    *,
    operation: str,
    submission_ambiguous: bool = False,
) -> BrokerExecutionError:
    if isinstance(error, BrokerExecutionError):
        return error

    status_code = getattr(error, "status_code", None)
    if status_code == 401:
        kind = BrokerErrorKind.AUTHENTICATION
    elif status_code == 403:
        kind = BrokerErrorKind.AUTHORIZATION
    elif status_code == 429:
        kind = BrokerErrorKind.RATE_LIMIT
    elif status_code in {400, 404, 405, 422}:
        kind = BrokerErrorKind.INVALID_REQUEST
    else:
        error_name = type(error).__name__.lower()
        if submission_ambiguous and any(
            value in error_name
            for value in (
                "timeout",
                "connection",
                "network",
                "retry",
            )
        ):
            kind = BrokerErrorKind.AMBIGUOUS_SUBMISSION
        elif any(
            value in error_name
            for value in (
                "timeout",
                "connection",
                "network",
                "retry",
            )
        ):
            kind = BrokerErrorKind.NETWORK
        elif submission_ambiguous:
            kind = BrokerErrorKind.AMBIGUOUS_SUBMISSION
        else:
            kind = BrokerErrorKind.UNKNOWN_BROKER_ERROR

    return BrokerExecutionError(
        kind,
        f"Alpaca {operation} failed ({kind.value}).",
    )


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
    def verify_paper_environment(
        self,
    ) -> PaperEnvironmentVerification:
        """Return isolated positive evidence for Alpaca paper mode."""

        return _paper_environment_evidence(self._client)

    def _require_paper_environment(self) -> None:
        verification = self.verify_paper_environment()
        if not verification.verified:
            raise BrokerExecutionError(
                BrokerErrorKind.AUTHORIZATION,
                verification.message,
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
            rejection_reason=(
                str(getattr(order, "reject_reason"))
                if getattr(
                    order,
                    "reject_reason",
                    None,
                )
                is not None
                else None
            ),
        )

    def submit_market_order(
        self,
        request: MarketOrderRequest,
    ) -> BrokerOrder:
        self._require_paper_environment()
        alpaca_side = (
            AlpacaOrderSide.BUY
            if request.side is OrderSide.BUY
            else AlpacaOrderSide.SELL
        )

        try:
            order_data = AlpacaMarketOrderRequest(
                symbol=request.symbol,
                qty=request.quantity,
                side=alpaca_side,
                time_in_force=TimeInForce.DAY,
                client_order_id=(
                    request.client_order_id
                ),
            )
        except Exception as exc:
            raise BrokerExecutionError(
                BrokerErrorKind.INVALID_REQUEST,
                "Alpaca order request could not be constructed.",
            ) from exc

        try:
            order = self._client.submit_order(
                order_data=order_data
            )
        except Exception as exc:
            raise _broker_error(
                exc,
                operation="order submission",
                submission_ambiguous=True,
            ) from exc
        return self._to_order(order)

    def get_order(
        self,
        order_id: str,
    ) -> BrokerOrder:
        try:
            order = self._client.get_order_by_id(order_id)
            return self._to_order(order)
        except Exception as exc:
            raise _broker_error(
                exc,
                operation="order lookup",
            ) from exc

    def find_order_by_client_id(
        self,
        client_order_id: str,
    ) -> BrokerOrder | None:
        try:
            order = self._client.get_order_by_client_id(
                client_order_id
            )
            return self._to_order(order)
        except Exception as exc:
            if (
                isinstance(exc, APIError)
                and _is_not_found(exc)
            ):
                return None
            raise _broker_error(
                exc,
                operation="client-order-id lookup",
            ) from exc

    def cancel_order(
        self,
        order_id: str,
    ) -> None:
        self._require_paper_environment()
        try:
            self._client.cancel_order_by_id(order_id)
        except Exception as exc:
            raise _broker_error(
                exc,
                operation="order cancellation",
                submission_ambiguous=True,
            ) from exc

    def get_account(self) -> AccountSnapshot:
        try:
            account = self._client.get_account()
            return AccountSnapshot(
                account_id=str(account.id),
                cash=_required_float(account.cash, "cash"),
                buying_power=_required_float(
                    account.buying_power,
                    "buying_power",
                ),
                equity=_required_float(account.equity, "equity"),
                trading_blocked=bool(account.trading_blocked),
                account_blocked=bool(account.account_blocked),
            )
        except Exception as exc:
            raise _broker_error(
                exc,
                operation="account lookup",
            ) from exc


    def get_clock(self) -> MarketClockSnapshot:
        try:
            clock = self._client.get_clock()
            return MarketClockSnapshot(
                timestamp=_required_datetime(
                    clock.timestamp,
                    "clock timestamp",
                ),
                is_open=bool(clock.is_open),
                next_open=_required_datetime(
                    clock.next_open,
                    "next open",
                ),
                next_close=_required_datetime(
                    clock.next_close,
                    "next close",
                ),
            )
        except Exception as exc:
            raise _broker_error(
                exc,
                operation="market-clock lookup",
            ) from exc

    def list_open_orders(
        self,
    ) -> list[BrokerOrder]:
        try:
            orders = self._client.get_orders(
                GetOrdersRequest(
                    status=QueryOrderStatus.OPEN,
                    limit=500,
                )
            )
            return [self._to_order(order) for order in orders]
        except Exception as exc:
            raise _broker_error(
                exc,
                operation="open-order lookup",
            ) from exc

    def list_positions(
        self,
    ) -> list[PositionSnapshot]:
        try:
            positions = self._client.get_all_positions()
            return [
                PositionSnapshot(
                    symbol=str(position.symbol).upper(),
                    quantity=_required_float(
                        position.qty,
                        "position qty",
                    ),
                    average_entry_price=_required_float(
                        position.avg_entry_price,
                        "average entry price",
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
        except Exception as exc:
            raise _broker_error(
                exc,
                operation="position lookup",
            ) from exc
