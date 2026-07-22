"""Coordinate strategy signals, risk checks, and paper execution."""

from __future__ import annotations

import math

from trading_bot.backtest.risk_manager import (
    RiskManager,
)
from trading_bot.broker.models import (
    MarketOrderRequest,
    OrderSide,
    PositionSnapshot,
)
from trading_bot.execution.client_ids import (
    build_order_client_order_id,
    build_order_intent_identity,
    build_position_generation_id,
)
from trading_bot.execution.decision_logging import (
    NullSignalDecisionLogger,
    SignalDecisionLogger,
)
from trading_bot.execution.models import (
    ExecutionOutcome,
)
from trading_bot.execution.position_state import (
    NullPositionStateStore,
    PositionStateStore,
)
from trading_bot.execution.risk_state import (
    NullRiskStateStore,
    RiskStateStore,
)
from trading_bot.execution.service import (
    PaperExecutionService,
)
from trading_bot.execution.signal_models import (
    SignalHandlingOutcome,
    SignalHandlingResult,
    StrategySignal,
    StrategySignalEvent,
)


HOLD_REASON = "hold_signal"
ALREADY_LONG_REASON = "already_long"
ALREADY_FLAT_REASON = "already_flat"
SHORT_POSITION_REASON = "short_position_not_supported"
FRACTIONAL_POSITION_REASON = "fractional_position_not_supported"
ACCOUNT_BLOCKED_REASON = "account_blocked"
TRADING_BLOCKED_REASON = "trading_blocked"
KILL_SWITCH_REASON = "kill_switch"
EXECUTION_ATTEMPTED_REASON = "execution_attempted"
BUYING_POWER_REASON = "insufficient_buying_power"
REFERENCE_PRICE_REASON = "reference_price_unavailable"
POSITION_OWNERSHIP_REASON = "position_ownership_uncertain"


class SignalExecutionCoordinator:
    """Turn deterministic strategy signals into safe paper orders."""

    def __init__(
        self,
        execution_service: PaperExecutionService,
        risk_manager: RiskManager,
        risk_state_store: RiskStateStore | None = None,
        position_state_store: PositionStateStore | None = None,
        logger: SignalDecisionLogger | None = None,
    ) -> None:
        self._execution_service = (
            execution_service
        )
        self._risk_manager = risk_manager
        self._risk_state_store = (
            risk_state_store
            if risk_state_store is not None
            else NullRiskStateStore()
        )
        self._position_state_store = (
            position_state_store
            if position_state_store is not None
            else NullPositionStateStore()
        )
        self._logger = (
            logger
            if logger is not None
            else NullSignalDecisionLogger()
        )

    def _finish(
        self,
        result: SignalHandlingResult,
    ) -> SignalHandlingResult:
        self._logger.log(result)
        return result

    def _position_for_symbol(
        self,
        symbol: str,
    ) -> PositionSnapshot | None:
        matches = [
            position
            for position
            in self._execution_service.list_positions()
            if position.symbol.upper() == symbol
        ]

        if not matches:
            return None

        if len(matches) > 1:
            raise RuntimeError(
                "Broker returned multiple positions "
                f"for {symbol}."
            )

        return matches[0]

    def _current_snapshot(
        self,
        event: StrategySignalEvent,
    ):
        return self._risk_manager.snapshot(
            event.signal_time
        )

    def _no_action(
        self,
        event: StrategySignalEvent,
        reason: str,
        position_quantity: float,
    ) -> SignalHandlingResult:
        return self._finish(
            SignalHandlingResult(
                event=event,
                outcome=(
                    SignalHandlingOutcome.NO_ACTION
                ),
                reason=reason,
                position_quantity_before=(
                    position_quantity
                ),
                risk_snapshot=(
                    self._current_snapshot(event)
                ),
            )
        )

    def _blocked(
        self,
        event: StrategySignalEvent,
        reason: str,
        position_quantity: float,
    ) -> SignalHandlingResult:
        return self._finish(
            SignalHandlingResult(
                event=event,
                outcome=(
                    SignalHandlingOutcome.BLOCKED
                ),
                reason=reason,
                position_quantity_before=(
                    position_quantity
                ),
                risk_snapshot=(
                    self._current_snapshot(event)
                ),
            )
        )

    @staticmethod
    def _whole_position_quantity(
        position: PositionSnapshot,
    ) -> int:
        quantity = position.quantity

        if (
            not math.isfinite(quantity)
            or quantity <= 0
            or not quantity.is_integer()
        ):
            raise ValueError(
                FRACTIONAL_POSITION_REASON
            )

        return int(quantity)

    def _record_filled_order(
        self,
        event: StrategySignalEvent,
        request: MarketOrderRequest,
        position: PositionSnapshot | None,
        execution_result,
    ) -> float | None:
        order = execution_result.order

        newly_filled_quantity = (
            execution_result.newly_filled_quantity
        )

        if (
            order is None
            or newly_filled_quantity <= 0
            or order.filled_average_price is None
        ):
            return None

        if request.side is OrderSide.BUY:
            self._risk_manager.record_entry(
                event.signal_time
            )
            self._risk_state_store.save(
                self._risk_manager
            )

            return None

        if position is None:
            return None

        if order.filled_average_price is None:
            return None

        realized_net_pnl = (
            order.filled_average_price
            - position.average_entry_price
        ) * newly_filled_quantity

        self._risk_manager.record_realized_pnl(
            session=event.signal_time,
            net_pnl=realized_net_pnl,
        )

        self._risk_state_store.save(
            self._risk_manager
        )

        return realized_net_pnl

    def handle(
        self,
        event: StrategySignalEvent,
    ) -> SignalHandlingResult:
        """Evaluate one signal and optionally attempt a paper order."""

        if event.signal is StrategySignal.HOLD:
            return self._no_action(
                event=event,
                reason=HOLD_REASON,
                position_quantity=0.0,
            )

        position = self._position_for_symbol(
            event.symbol
        )

        position_quantity = (
            position.quantity
            if position is not None
            else 0.0
        )

        if position_quantity < 0:
            return self._blocked(
                event=event,
                reason=SHORT_POSITION_REASON,
                position_quantity=(
                    position_quantity
                ),
            )

        if (
            event.signal
            is StrategySignal.ENTER_LONG
            and position_quantity > 0
        ):
            return self._no_action(
                event=event,
                reason=ALREADY_LONG_REASON,
                position_quantity=(
                    position_quantity
                ),
            )

        if (
            event.signal
            is StrategySignal.EXIT_LONG
            and position_quantity == 0
        ):
            return self._no_action(
                event=event,
                reason=ALREADY_FLAT_REASON,
                position_quantity=0.0,
            )

        account = (
            self._execution_service.get_account()
        )

        if account.account_blocked:
            return self._blocked(
                event=event,
                reason=ACCOUNT_BLOCKED_REASON,
                position_quantity=(
                    position_quantity
                ),
            )

        if account.trading_blocked:
            return self._blocked(
                event=event,
                reason=TRADING_BLOCKED_REASON,
                position_quantity=(
                    position_quantity
                ),
            )

        if event.signal is StrategySignal.ENTER_LONG:
            if event.reference_price is None:
                return self._blocked(
                    event=event,
                    reason=REFERENCE_PRICE_REASON,
                    position_quantity=position_quantity,
                )

            requested_notional = (
                event.reference_price
                * event.entry_quantity
            )
            if (
                not math.isfinite(account.buying_power)
                or account.buying_power
                < requested_notional
            ):
                return self._blocked(
                    event=event,
                    reason=BUYING_POWER_REASON,
                    position_quantity=position_quantity,
                )

            risk_decision = (
                self._risk_manager
                .evaluate_entry(
                    event.signal_time
                )
            )

            if not risk_decision.allowed:
                return self._finish(
                    SignalHandlingResult(
                        event=event,
                        outcome=(
                            SignalHandlingOutcome.BLOCKED
                        ),
                        reason=(
                            risk_decision.reason
                            or "risk_control"
                        ),
                        position_quantity_before=(
                            position_quantity
                        ),
                        risk_snapshot=(
                            risk_decision.snapshot
                        ),
                    )
                )

            side = OrderSide.BUY
            quantity = event.entry_quantity
            position_generation_id = (
                build_position_generation_id(
                    strategy_name=event.strategy_name,
                    symbol=event.symbol,
                    timeframe_minutes=(
                        event.timeframe_minutes
                    ),
                    signal_bar_end=(
                        event.action_identity_time
                    ),
                )
            )

        else:
            side = OrderSide.SELL

            assert position is not None

            try:
                quantity = (
                    self._whole_position_quantity(
                        position
                    )
                )
            except ValueError:
                return self._blocked(
                    event=event,
                    reason=(
                        FRACTIONAL_POSITION_REASON
                    ),
                    position_quantity=(
                        position_quantity
                    ),
                )

            tracked_position = (
                self._position_state_store.load(
                    event.symbol
                )
            )
            position_generation_id = (
                tracked_position.position_generation_id
                if tracked_position is not None
                else None
            )
            if (
                tracked_position is None
                or tracked_position.legacy_open
                or not position_generation_id
            ):
                return self._blocked(
                    event=event,
                    reason=POSITION_OWNERSHIP_REASON,
                    position_quantity=position_quantity,
                )

        intent_id = build_order_intent_identity(
            strategy_name=event.strategy_name,
            symbol=event.symbol,
            timeframe_minutes=event.timeframe_minutes,
            signal_bar_end=event.action_identity_time,
            action=event.action_name,
            position_generation_id=(
                position_generation_id
            ),
        )
        client_order_id = build_order_client_order_id(
            intent_id=intent_id,
            strategy_name=event.strategy_name,
            symbol=event.symbol,
            side=side,
            action=event.action_name,
        )

        request = MarketOrderRequest(
            symbol=event.symbol,
            quantity=quantity,
            side=side,
            client_order_id=(
                client_order_id
            ),
        )

        execution_result = (
            self._execution_service
            .execute_market_order(
                request,
                strategy_name=event.strategy_name,
                timeframe_minutes=(
                    event.timeframe_minutes
                ),
                signal_bar_end=(
                    event.action_identity_time
                ),
                action=event.action_name,
                position_generation_id=(
                    position_generation_id
                ),
            )
        )

        realized_net_pnl = (
            self._record_filled_order(
                event=event,
                request=request,
                position=position,
                execution_result=(
                    execution_result
                ),
            )
        )

        if (
            execution_result.outcome
            is ExecutionOutcome.BLOCKED
        ):
            outcome = (
                SignalHandlingOutcome.BLOCKED
            )
            reason = KILL_SWITCH_REASON
        else:
            outcome = (
                SignalHandlingOutcome
                .ORDER_ATTEMPTED
            )
            reason = EXECUTION_ATTEMPTED_REASON

        return self._finish(
            SignalHandlingResult(
                event=event,
                outcome=outcome,
                reason=reason,
                position_quantity_before=(
                    position_quantity
                ),
                risk_snapshot=(
                    self._current_snapshot(event)
                ),
                request=request,
                execution_result=(
                    execution_result
                ),
                realized_net_pnl_recorded=(
                    realized_net_pnl
                ),
            )
        )
