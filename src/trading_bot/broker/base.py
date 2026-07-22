"""Broker interface consumed by the execution service."""

from __future__ import annotations

from typing import Protocol

from trading_bot.broker.models import (
    AccountSnapshot,
    BrokerOrder,
    MarketClockSnapshot,
    MarketOrderRequest,
    PositionSnapshot,
    PaperEnvironmentVerification,
)


class PaperBroker(Protocol):
    """Minimal broker contract required for safe paper execution."""

    def verify_paper_environment(
        self,
    ) -> PaperEnvironmentVerification:
        """Return positive or negative paper-environment evidence."""

    def submit_market_order(
        self,
        request: MarketOrderRequest,
    ) -> BrokerOrder:
        """Submit a market order to the paper broker."""

    def get_order(
        self,
        order_id: str,
    ) -> BrokerOrder:
        """Return the latest state for one order."""

    def find_order_by_client_id(
        self,
        client_order_id: str,
    ) -> BrokerOrder | None:
        """Return an existing order or None when it is absent."""

    def cancel_order(
        self,
        order_id: str,
    ) -> None:
        """Request cancellation of an open order."""

    def get_account(self) -> AccountSnapshot:
        """Return the current paper-account state."""

    def get_clock(self) -> MarketClockSnapshot:
        """Return the current regular-market clock."""

    def list_open_orders(
        self,
    ) -> list[BrokerOrder]:
        """Return all currently open paper orders."""

    def list_positions(
        self,
    ) -> list[PositionSnapshot]:
        """Return all open paper positions."""
