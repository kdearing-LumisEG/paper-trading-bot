"""Safe, broker-neutral paper-order execution service."""

from __future__ import annotations

import time
from typing import Callable

from trading_bot.broker.base import PaperBroker
from trading_bot.broker.models import (
    AccountSnapshot,
    BrokerOrder,
    BrokerOrderStatus,
    MarketClockSnapshot,
    MarketOrderRequest,
    PositionSnapshot,
)
from trading_bot.execution.kill_switch import (
    KillSwitch,
    StaticKillSwitch,
)
from trading_bot.execution.logging import (
    ExecutionLogger,
    NullExecutionLogger,
)
from trading_bot.execution.models import (
    ExecutionOutcome,
    ExecutionResult,
    ExecutionSettings,
)


class PaperExecutionService:
    """Submit idempotent paper orders and confirm terminal state."""

    def __init__(
        self,
        broker: PaperBroker,
        settings: ExecutionSettings | None = None,
        kill_switch: KillSwitch | None = None,
        logger: ExecutionLogger | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._broker = broker
        self._settings = (
            settings
            if settings is not None
            else ExecutionSettings()
        )
        self._kill_switch = (
            kill_switch
            if kill_switch is not None
            else StaticKillSwitch()
        )
        self._logger = (
            logger
            if logger is not None
            else NullExecutionLogger()
        )
        self._sleeper = sleeper

    def _finish(
        self,
        result: ExecutionResult,
    ) -> ExecutionResult:
        self._logger.log(result)
        return result

    @staticmethod
    def _terminal_result(
        request: MarketOrderRequest,
        order: BrokerOrder,
        poll_count: int,
    ) -> ExecutionResult:
        if order.status is BrokerOrderStatus.FILLED:
            return ExecutionResult(
                request=request,
                outcome=ExecutionOutcome.FILLED,
                message="Paper order filled.",
                order=order,
                poll_count=poll_count,
            )

        return ExecutionResult(
            request=request,
            outcome=ExecutionOutcome.TERMINAL,
            message=(
                "Paper order reached terminal status: "
                f"{order.status.value}."
            ),
            order=order,
            poll_count=poll_count,
        )

    def execute_market_order(
        self,
        request: MarketOrderRequest,
    ) -> ExecutionResult:
        """Safely submit or simulate one paper market order."""

        if self._kill_switch.is_active():
            return self._finish(
                ExecutionResult(
                    request=request,
                    outcome=ExecutionOutcome.BLOCKED,
                    message=(
                        "Execution blocked by the emergency "
                        "kill switch."
                    ),
                )
            )

        existing_order = (
            self._broker.find_order_by_client_id(
                request.client_order_id
            )
        )

        if existing_order is not None:
            return self._finish(
                ExecutionResult(
                    request=request,
                    outcome=ExecutionOutcome.DUPLICATE,
                    message=(
                        "An order already exists for this "
                        "client_order_id."
                    ),
                    order=existing_order,
                )
            )

        if self._settings.dry_run:
            return self._finish(
                ExecutionResult(
                    request=request,
                    outcome=ExecutionOutcome.DRY_RUN,
                    message=(
                        "Dry run completed; no order was "
                        "submitted."
                    ),
                )
            )

        order = self._broker.submit_market_order(
            request
        )

        if order.status.is_terminal:
            return self._finish(
                self._terminal_result(
                    request=request,
                    order=order,
                    poll_count=0,
                )
            )

        latest_order = order

        for poll_count in range(
            1,
            self._settings.max_poll_attempts + 1,
        ):
            if self._settings.poll_interval_seconds > 0:
                self._sleeper(
                    self._settings.poll_interval_seconds
                )

            latest_order = self._broker.get_order(
                order.order_id
            )

            if latest_order.status.is_terminal:
                return self._finish(
                    self._terminal_result(
                        request=request,
                        order=latest_order,
                        poll_count=poll_count,
                    )
                )

        cancellation_requested = False

        if self._settings.cancel_on_timeout:
            self._broker.cancel_order(
                order.order_id
            )
            cancellation_requested = True

        return self._finish(
            ExecutionResult(
                request=request,
                outcome=ExecutionOutcome.TIMEOUT,
                message=(
                    "Order did not reach a terminal status "
                    "within the polling limit."
                ),
                order=latest_order,
                poll_count=(
                    self._settings.max_poll_attempts
                ),
                cancellation_requested=(
                    cancellation_requested
                ),
            )
        )

    def get_account(self) -> AccountSnapshot:
        """Return the latest paper-account snapshot."""

        return self._broker.get_account()

    def get_clock(self) -> MarketClockSnapshot:
        """Return the latest regular-market clock."""

        return self._broker.get_clock()

    def list_positions(
        self,
    ) -> list[PositionSnapshot]:
        """Return all current paper positions."""

        return self._broker.list_positions()
