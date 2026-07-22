"""Durable, broker-neutral Alpaca paper-order execution service."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import math
import time
from typing import Callable

from trading_bot.broker.base import PaperBroker
from trading_bot.broker.models import (
    AccountSnapshot,
    BrokerErrorKind,
    BrokerExecutionError,
    BrokerOrder,
    BrokerOrderStatus,
    MarketClockSnapshot,
    MarketOrderRequest,
    OrderSide,
    PaperEnvironmentVerification,
    PositionSnapshot,
)
from trading_bot.execution.client_ids import (
    build_order_client_order_id,
    build_order_intent_identity,
    build_position_generation_id,
)
from trading_bot.execution.kill_switch import (
    KillSwitch,
    StaticKillSwitch,
)
from trading_bot.execution.logging import (
    ExecutionLogger,
    NullExecutionLogger,
    NullOrderLifecycleLogger,
    OrderLifecycleEvent,
    OrderLifecycleLogger,
)
from trading_bot.execution.models import (
    ExecutionOutcome,
    ExecutionResult,
    ExecutionSettings,
)
from trading_bot.execution.order_state import (
    NullOrderStateStore,
    OrderIntent,
    OrderLifecycleState,
    OrderStateError,
    OrderStateStore,
)
from trading_bot.execution.position_state import (
    NullPositionStateStore,
    PositionPhase,
    PositionStateStore,
    TrackedPosition,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _lifecycle_for_order(
    order: BrokerOrder,
) -> OrderLifecycleState:
    mapping = {
        BrokerOrderStatus.NEW: OrderLifecycleState.SUBMITTED,
        BrokerOrderStatus.PENDING_NEW: (
            OrderLifecycleState.SUBMITTED
        ),
        BrokerOrderStatus.ACCEPTED: (
            OrderLifecycleState.ACCEPTED
        ),
        BrokerOrderStatus.PARTIALLY_FILLED: (
            OrderLifecycleState.PARTIALLY_FILLED
        ),
        BrokerOrderStatus.FILLED: OrderLifecycleState.FILLED,
        BrokerOrderStatus.CANCELED: (
            OrderLifecycleState.CANCELED
        ),
        BrokerOrderStatus.REJECTED: (
            OrderLifecycleState.REJECTED
        ),
        BrokerOrderStatus.EXPIRED: OrderLifecycleState.EXPIRED,
    }
    return mapping.get(
        order.status,
        OrderLifecycleState.RECONCILIATION_REQUIRED,
    )


def advance_intent_from_broker_order(
    intent: OrderIntent,
    order: BrokerOrder,
    *,
    checked_at: datetime,
) -> OrderIntent:
    """Return a monotonic lifecycle snapshot from broker-confirmed data."""

    if (
        order.client_order_id != intent.client_order_id
        or order.symbol.upper() != intent.symbol
        or order.side is not intent.side
        or order.quantity != intent.requested_quantity
    ):
        return replace(
            intent,
            lifecycle_state=(
                OrderLifecycleState.RECONCILIATION_REQUIRED
            ),
            updated_at=checked_at,
            last_reconciled_at=checked_at,
            last_error_type="broker_order_mismatch",
            last_error_message=(
                "Broker order fields do not match the durable intent."
            ),
        )

    if (
        not math.isfinite(order.filled_quantity)
        or order.filled_quantity < intent.filled_quantity
        or order.filled_quantity > intent.requested_quantity
    ):
        return replace(
            intent,
            lifecycle_state=(
                OrderLifecycleState.RECONCILIATION_REQUIRED
            ),
            updated_at=checked_at,
            last_reconciled_at=checked_at,
            last_error_type="nonmonotonic_fill",
            last_error_message=(
                "Broker fill quantity is invalid or moved backward."
            ),
        )

    state = _lifecycle_for_order(order)
    if state is not OrderLifecycleState.RECONCILIATION_REQUIRED:
        if order.filled_quantity == intent.requested_quantity:
            state = OrderLifecycleState.FILLED
        elif (
            order.filled_quantity > 0
            and not state.is_terminal
        ):
            state = OrderLifecycleState.PARTIALLY_FILLED

    progress = {
        OrderLifecycleState.CREATED: 0,
        OrderLifecycleState.SUBMITTING: 1,
        OrderLifecycleState.SUBMITTED: 2,
        OrderLifecycleState.ACCEPTED: 3,
        OrderLifecycleState.PARTIALLY_FILLED: 4,
    }
    if (
        intent.lifecycle_state in progress
        and state in progress
        and progress[state] < progress[intent.lifecycle_state]
    ):
        state = intent.lifecycle_state
    elif (
        intent.lifecycle_state.is_terminal
        and state is not intent.lifecycle_state
    ):
        state = OrderLifecycleState.RECONCILIATION_REQUIRED
    average_fill_price = order.filled_average_price
    if order.filled_quantity > 0 and average_fill_price is None:
        state = OrderLifecycleState.RECONCILIATION_REQUIRED

    terminal_at = (
        checked_at
        if state.is_terminal
        else None
    )

    return replace(
        intent,
        lifecycle_state=state,
        broker_order_id=order.order_id,
        broker_status=order.status.value,
        filled_quantity=order.filled_quantity,
        average_fill_price=average_fill_price,
        submitted_at=(
            order.submitted_at
            or intent.submitted_at
            or checked_at
        ),
        updated_at=checked_at,
        last_reconciled_at=checked_at,
        terminal_at=terminal_at,
        rejection_reason=order.rejection_reason,
        last_error_type=(
            "unknown_broker_status"
            if state
            is OrderLifecycleState.RECONCILIATION_REQUIRED
            else None
        ),
        last_error_message=(
            "Broker status could not be mapped safely."
            if state
            is OrderLifecycleState.RECONCILIATION_REQUIRED
            else None
        ),
    )


def apply_confirmed_intent_to_position(
    intent: OrderIntent,
    position_state_store: PositionStateStore,
    *,
    checked_at: datetime,
) -> TrackedPosition:
    """Persist position ownership derived only from confirmed fill data."""

    current = position_state_store.load(intent.symbol)
    ambiguous = intent.lifecycle_state is (
        OrderLifecycleState.RECONCILIATION_REQUIRED
    )

    if intent.side is OrderSide.BUY:
        if (
            current is not None
            and (
                current.legacy_open
                or (
                    current.phase is not PositionPhase.FLAT
                    and current.position_generation_id
                    != intent.position_generation_id
                )
            )
        ):
            raise OrderStateError(
                "Entry intent conflicts with an existing position generation."
            )
        if intent.filled_quantity > 0:
            position = TrackedPosition(
                schema_version=2,
                symbol=intent.symbol,
                strategy_name=intent.strategy_name,
                position_generation_id=(
                    intent.position_generation_id
                ),
                phase=(
                    PositionPhase.RECONCILIATION_REQUIRED
                    if ambiguous
                    else PositionPhase.OPEN
                ),
                quantity=intent.filled_quantity,
                average_entry_price=(
                    intent.average_fill_price
                ),
                updated_at=checked_at,
                source_order_id=intent.broker_order_id,
                source_client_order_id=(
                    intent.client_order_id
                ),
                entry_intent_id=intent.intent_id,
                entry_client_order_id=(
                    intent.client_order_id
                ),
                entry_broker_order_id=(
                    intent.broker_order_id
                ),
                entry_filled_at=(
                    checked_at
                    if intent.lifecycle_state.is_terminal
                    else (
                        current.entry_filled_at
                        if current is not None
                        else None
                    )
                ),
                last_reconciled_at=(
                    intent.last_reconciled_at
                ),
            )
        elif intent.lifecycle_state.is_terminal:
            position = TrackedPosition.flat(
                schema_version=2,
                symbol=intent.symbol,
                strategy_name=intent.strategy_name,
                position_generation_id=(
                    intent.position_generation_id
                ),
                updated_at=checked_at,
                entry_intent_id=intent.intent_id,
                entry_client_order_id=(
                    intent.client_order_id
                ),
                entry_broker_order_id=(
                    intent.broker_order_id
                ),
                last_reconciled_at=(
                    intent.last_reconciled_at
                ),
            )
        else:
            position = TrackedPosition(
                schema_version=2,
                symbol=intent.symbol,
                strategy_name=intent.strategy_name,
                position_generation_id=(
                    intent.position_generation_id
                ),
                phase=(
                    PositionPhase.RECONCILIATION_REQUIRED
                    if ambiguous
                    else PositionPhase.ENTRY_PENDING
                ),
                quantity=0.0,
                average_entry_price=None,
                updated_at=checked_at,
                entry_intent_id=intent.intent_id,
                entry_client_order_id=(
                    intent.client_order_id
                ),
                entry_broker_order_id=(
                    intent.broker_order_id
                ),
                last_reconciled_at=(
                    intent.last_reconciled_at
                ),
            )
    else:
        if current is None:
            raise OrderStateError(
                "An exit intent has no owned position state."
            )
        if (
            current.legacy_open
            or current.position_generation_id
            != intent.position_generation_id
        ):
            raise OrderStateError(
                "Exit intent position generation does not match ownership."
            )
        if (
            current.exit_intent_id not in {None, intent.intent_id}
            or (
                current.exit_intent_id is None
                and intent.filled_quantity == 0
                and current.quantity
                != float(intent.requested_quantity)
            )
        ):
            raise OrderStateError(
                "Exit intent does not match the owned position quantity."
            )

        remaining = max(
            0.0,
            float(intent.requested_quantity)
            - intent.filled_quantity,
        )
        if remaining == 0:
            position = TrackedPosition.flat(
                schema_version=2,
                symbol=current.symbol,
                strategy_name=current.strategy_name,
                position_generation_id=(
                    current.position_generation_id
                ),
                updated_at=checked_at,
                source_order_id=intent.broker_order_id,
                source_client_order_id=(
                    intent.client_order_id
                ),
                entry_intent_id=current.entry_intent_id,
                entry_client_order_id=(
                    current.entry_client_order_id
                ),
                entry_broker_order_id=(
                    current.entry_broker_order_id
                ),
                entry_filled_at=current.entry_filled_at,
                exit_intent_id=intent.intent_id,
                exit_client_order_id=(
                    intent.client_order_id
                ),
                exit_broker_order_id=(
                    intent.broker_order_id
                ),
                exit_filled_at=checked_at,
                last_reconciled_at=(
                    intent.last_reconciled_at
                ),
            )
        else:
            position = TrackedPosition(
                schema_version=2,
                symbol=current.symbol,
                strategy_name=current.strategy_name,
                position_generation_id=(
                    current.position_generation_id
                ),
                phase=(
                    PositionPhase.RECONCILIATION_REQUIRED
                    if ambiguous
                    else (
                        PositionPhase.OPEN
                        if intent.filled_quantity > 0
                        or intent.lifecycle_state.is_terminal
                        else PositionPhase.EXIT_PENDING
                    )
                ),
                quantity=remaining,
                average_entry_price=(
                    current.average_entry_price
                ),
                updated_at=checked_at,
                source_order_id=current.source_order_id,
                source_client_order_id=(
                    current.source_client_order_id
                ),
                entry_intent_id=current.entry_intent_id,
                entry_client_order_id=(
                    current.entry_client_order_id
                ),
                entry_broker_order_id=(
                    current.entry_broker_order_id
                ),
                entry_filled_at=current.entry_filled_at,
                exit_intent_id=intent.intent_id,
                exit_client_order_id=(
                    intent.client_order_id
                ),
                exit_broker_order_id=(
                    intent.broker_order_id
                ),
                last_reconciled_at=(
                    intent.last_reconciled_at
                ),
            )

    position_state_store.save(position)
    return position


class PaperExecutionService:
    """Persist, submit once, and reconcile paper market-order intents."""

    def __init__(
        self,
        broker: PaperBroker,
        settings: ExecutionSettings | None = None,
        kill_switch: KillSwitch | None = None,
        logger: ExecutionLogger | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        order_state_store: OrderStateStore | None = None,
        position_state_store: PositionStateStore | None = None,
        lifecycle_logger: OrderLifecycleLogger | None = None,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._broker = broker
        self._settings = settings or ExecutionSettings()
        self._kill_switch = kill_switch or StaticKillSwitch()
        self._logger = logger or NullExecutionLogger()
        self._sleeper = sleeper
        self._order_state_store = (
            order_state_store or NullOrderStateStore()
        )
        self._position_state_store = (
            position_state_store or NullPositionStateStore()
        )
        self._lifecycle_logger = (
            lifecycle_logger or NullOrderLifecycleLogger()
        )
        self._now = now
        self._audit_errors: list[str] = []

    def _finish(self, result: ExecutionResult) -> ExecutionResult:
        try:
            self._logger.log(result)
        except Exception as exc:
            self._audit_errors.append(
                f"execution_log:{type(exc).__name__}"
            )

        if self._audit_errors:
            result = replace(
                result,
                audit_logging_error=",".join(
                    self._audit_errors
                ),
            )
        return result

    def _emit(
        self,
        event_type: str,
        intent: OrderIntent,
        *,
        message: str | None = None,
    ) -> None:
        try:
            self._lifecycle_logger.log_event(
                OrderLifecycleEvent(
                    event_type=event_type,
                    timestamp=self._now(),
                    intent_id=intent.intent_id,
                    client_order_id=(
                        intent.client_order_id
                    ),
                    broker_order_id=(
                        intent.broker_order_id
                    ),
                    position_generation_id=(
                        intent.position_generation_id
                    ),
                    strategy_name=intent.strategy_name,
                    symbol=intent.symbol,
                    action=intent.action,
                    lifecycle_state=(
                        intent.lifecycle_state.value
                    ),
                    filled_quantity=(
                        intent.filled_quantity
                    ),
                    message=message,
                )
            )
        except Exception as exc:
            self._audit_errors.append(
                f"lifecycle_log:{type(exc).__name__}"
            )

    def verify_paper_environment(
        self,
    ) -> PaperEnvironmentVerification:
        return self._broker.verify_paper_environment()

    def _result_for_intent(
        self,
        *,
        request: MarketOrderRequest,
        intent: OrderIntent,
        order: BrokerOrder | None,
        poll_count: int,
        newly_filled_quantity: float,
        cancellation_requested: bool = False,
    ) -> ExecutionResult:
        state = intent.lifecycle_state
        if state is OrderLifecycleState.FILLED:
            outcome = ExecutionOutcome.FILLED
            message = "Paper order filled."
        elif state is (
            OrderLifecycleState.RECONCILIATION_REQUIRED
        ):
            outcome = ExecutionOutcome.RECONCILIATION_REQUIRED
            message = (
                "Order state is uncertain and requires reconciliation."
            )
        elif state.is_terminal:
            outcome = ExecutionOutcome.TERMINAL
            message = (
                "Paper order reached terminal state: "
                f"{state.value}."
            )
        else:
            outcome = ExecutionOutcome.TIMEOUT
            message = (
                "Paper order remains nonterminal after polling."
            )

        return self._finish(
            ExecutionResult(
                request=request,
                outcome=outcome,
                message=message,
                order=order,
                poll_count=poll_count,
                cancellation_requested=(
                    cancellation_requested
                ),
                intent_id=intent.intent_id,
                lifecycle_state=state.value,
                newly_filled_quantity=(
                    newly_filled_quantity
                ),
            )
        )

    def _persist_broker_state(
        self,
        intent: OrderIntent,
        order: BrokerOrder,
    ) -> tuple[OrderIntent, float]:
        previous_fill = intent.filled_quantity
        checked_at = self._now()
        advanced = advance_intent_from_broker_order(
            intent,
            order,
            checked_at=checked_at,
        )
        order_persistence_error: Exception | None = None
        try:
            self._order_state_store.save(advanced)
        except Exception as exc:
            order_persistence_error = exc

        try:
            before = self._position_state_store.load(
                advanced.symbol
            )
            position = apply_confirmed_intent_to_position(
                advanced,
                self._position_state_store,
                checked_at=checked_at,
            )
        except Exception as exc:
            uncertain = replace(
                advanced,
                lifecycle_state=(
                    OrderLifecycleState
                    .RECONCILIATION_REQUIRED
                ),
                updated_at=checked_at,
                last_error_type="position_persistence_failure",
                last_error_message=(
                    "Confirmed broker state could not be persisted "
                    "to position ownership."
                ),
            )
            try:
                self._order_state_store.save(uncertain)
            except Exception:
                pass
            self._emit(
                "order_reconciliation_required",
                uncertain,
                message=type(exc).__name__,
            )
            return uncertain, max(
                0.0,
                advanced.filled_quantity - previous_fill,
            )

        if order_persistence_error is not None:
            uncertain = replace(
                advanced,
                lifecycle_state=(
                    OrderLifecycleState.RECONCILIATION_REQUIRED
                ),
                updated_at=checked_at,
                last_error_type="order_persistence_failure",
                last_error_message=(
                    "Broker state could not be durably persisted."
                ),
            )
            try:
                self._order_state_store.save(uncertain)
            except Exception:
                pass
            self._emit(
                "order_reconciliation_required",
                uncertain,
                message=type(order_persistence_error).__name__,
            )
            return uncertain, max(
                0.0,
                advanced.filled_quantity - previous_fill,
            )

        event_type = {
            OrderLifecycleState.PARTIALLY_FILLED: (
                "order_partial_fill"
            ),
            OrderLifecycleState.FILLED: "order_filled",
            OrderLifecycleState.CANCELED: "order_canceled",
            OrderLifecycleState.REJECTED: "order_rejected",
            OrderLifecycleState.EXPIRED: "order_expired",
            OrderLifecycleState.RECONCILIATION_REQUIRED: (
                "order_reconciliation_required"
            ),
        }.get(
            advanced.lifecycle_state,
            "order_status_changed",
        )
        self._emit(event_type, advanced)

        if before is None and position.quantity > 0:
            self._emit(
                "position_generation_created",
                advanced,
            )
        elif (
            before is not None
            and before.quantity != position.quantity
        ):
            self._emit(
                (
                    "position_closed"
                    if position.quantity == 0
                    else "position_quantity_changed"
                ),
                advanced,
            )

        return advanced, max(
            0.0,
            advanced.filled_quantity - previous_fill,
        )

    def reconcile_order_intent(
        self,
        intent: OrderIntent,
    ) -> OrderIntent:
        """Advance one existing intent without ever resubmitting it."""

        try:
            order = self._broker.find_order_by_client_id(
                intent.client_order_id
            )
        except BrokerExecutionError as exc:
            uncertain = replace(
                intent,
                lifecycle_state=(
                    OrderLifecycleState
                    .RECONCILIATION_REQUIRED
                ),
                updated_at=self._now(),
                last_error_type=exc.kind.value,
                last_error_message=str(exc),
            )
            self._order_state_store.save(uncertain)
            return uncertain

        if order is None:
            uncertain = replace(
                intent,
                lifecycle_state=(
                    OrderLifecycleState
                    .RECONCILIATION_REQUIRED
                ),
                updated_at=self._now(),
                last_reconciled_at=self._now(),
                last_error_type="broker_absence_unproven",
                last_error_message=(
                    "Broker lookup did not prove the order was never accepted."
                ),
            )
            self._order_state_store.save(uncertain)
            self._emit(
                "order_reconciliation_required",
                uncertain,
            )
            return uncertain

        advanced, _ = self._persist_broker_state(intent, order)
        return advanced

    def reconcile_known_order(
        self,
        intent: OrderIntent,
        order: BrokerOrder,
    ) -> OrderIntent:
        """Persist a broker order already fetched by reconciliation."""

        advanced, _ = self._persist_broker_state(
            intent,
            order,
        )
        return advanced

    def _recover_submission_error(
        self,
        *,
        intent: OrderIntent,
        request: MarketOrderRequest,
        error: BrokerExecutionError,
    ) -> ExecutionResult:
        now = self._now()
        if error.kind is (
            BrokerErrorKind.TIMEOUT_BEFORE_TRANSMISSION
        ):
            failed = replace(
                intent,
                lifecycle_state=OrderLifecycleState.REJECTED,
                updated_at=now,
                terminal_at=now,
                rejection_reason=(
                    "Submission was not transmitted."
                ),
                last_error_type=error.kind.value,
                last_error_message=str(error),
            )
            self._order_state_store.save(failed)
            apply_confirmed_intent_to_position(
                failed,
                self._position_state_store,
                checked_at=now,
            )
            self._emit("order_rejected", failed)
            return self._result_for_intent(
                request=request,
                intent=failed,
                order=None,
                poll_count=0,
                newly_filled_quantity=0.0,
            )

        if error.kind in {
            BrokerErrorKind.AUTHENTICATION,
            BrokerErrorKind.AUTHORIZATION,
            BrokerErrorKind.RATE_LIMIT,
            BrokerErrorKind.BROKER_REJECTION,
            BrokerErrorKind.INVALID_REQUEST,
        }:
            failed = replace(
                intent,
                lifecycle_state=OrderLifecycleState.REJECTED,
                updated_at=now,
                terminal_at=now,
                rejection_reason="Broker rejected the submission.",
                last_error_type=error.kind.value,
                last_error_message=str(error),
            )
            self._order_state_store.save(failed)
            apply_confirmed_intent_to_position(
                failed,
                self._position_state_store,
                checked_at=now,
            )
            self._emit("order_rejected", failed)
            return self._result_for_intent(
                request=request,
                intent=failed,
                order=None,
                poll_count=0,
                newly_filled_quantity=0.0,
            )

        uncertain = replace(
            intent,
            lifecycle_state=(
                OrderLifecycleState.RECONCILIATION_REQUIRED
            ),
            updated_at=now,
            last_error_type=error.kind.value,
            last_error_message=str(error),
        )
        self._order_state_store.save(uncertain)
        self._emit("order_submission_ambiguous", uncertain)

        recovered = self.reconcile_order_intent(uncertain)
        return self._result_for_intent(
            request=request,
            intent=recovered,
            order=None,
            poll_count=0,
            newly_filled_quantity=max(
                0.0,
                recovered.filled_quantity
                - intent.filled_quantity,
            ),
        )

    def execute_market_order(
        self,
        request: MarketOrderRequest,
        *,
        strategy_name: str = "compatibility",
        timeframe_minutes: int = 1,
        signal_bar_end: datetime | None = None,
        action: str | None = None,
        position_generation_id: str | None = None,
    ) -> ExecutionResult:
        """Simulate or durably submit one paper market order."""

        self._audit_errors = []
        if self._kill_switch.is_active():
            return self._finish(
                ExecutionResult(
                    request=request,
                    outcome=ExecutionOutcome.BLOCKED,
                    message=(
                        "Execution blocked by the emergency kill switch."
                    ),
                )
            )

        existing_broker_order = (
            self._broker.find_order_by_client_id(
                request.client_order_id
            )
        )
        if existing_broker_order is not None:
            return self._finish(
                ExecutionResult(
                    request=request,
                    outcome=ExecutionOutcome.DUPLICATE,
                    message=(
                        "An order already exists for this client_order_id."
                    ),
                    order=existing_broker_order,
                )
            )

        if self._settings.dry_run:
            return self._finish(
                ExecutionResult(
                    request=request,
                    outcome=ExecutionOutcome.DRY_RUN,
                    message=(
                        "Dry run completed; no order was submitted."
                    ),
                )
            )

        verification = self.verify_paper_environment()
        if not verification.verified:
            return self._finish(
                ExecutionResult(
                    request=request,
                    outcome=ExecutionOutcome.BLOCKED,
                    message=verification.message,
                )
            )

        if not getattr(
            self._order_state_store,
            "durable",
            False,
        ):
            return self._finish(
                ExecutionResult(
                    request=request,
                    outcome=ExecutionOutcome.BLOCKED,
                    message=(
                        "Durable order-state storage is required for execution."
                    ),
                )
            )

        action = action or (
            "enter_long"
            if request.side is OrderSide.BUY
            else "exit_long"
        )
        signal_bar_end = signal_bar_end or self._now()
        if position_generation_id is None:
            if request.side is OrderSide.BUY:
                position_generation_id = (
                    build_position_generation_id(
                        strategy_name=strategy_name,
                        symbol=request.symbol,
                        timeframe_minutes=timeframe_minutes,
                        signal_bar_end=signal_bar_end,
                    )
                )
            else:
                tracked = self._position_state_store.load(
                    request.symbol
                )
                position_generation_id = (
                    tracked.position_generation_id
                    if tracked is not None
                    else None
                )
                if not position_generation_id:
                    return self._finish(
                        ExecutionResult(
                            request=request,
                            outcome=ExecutionOutcome.BLOCKED,
                            message=(
                                "Exit execution requires generation-aware "
                                "owned position state."
                            ),
                        )
                    )

        intent_id = build_order_intent_identity(
            strategy_name=strategy_name,
            symbol=request.symbol,
            timeframe_minutes=timeframe_minutes,
            signal_bar_end=signal_bar_end,
            action=action,
            position_generation_id=(
                position_generation_id
            ),
        )
        durable_client_id = build_order_client_order_id(
            intent_id=intent_id,
            strategy_name=strategy_name,
            symbol=request.symbol,
            side=request.side,
            action=action,
        )
        durable_request = MarketOrderRequest(
            symbol=request.symbol,
            quantity=request.quantity,
            side=request.side,
            client_order_id=durable_client_id,
        )

        existing = self._order_state_store.get_by_intent_id(
            intent_id
        )
        if existing is not None:
            recovered = (
                existing
                if existing.lifecycle_state.is_terminal
                else self.reconcile_order_intent(existing)
            )
            return self._result_for_intent(
                request=durable_request,
                intent=recovered,
                order=None,
                poll_count=0,
                newly_filled_quantity=0.0,
            )

        unresolved_intents = (
            self._order_state_store.list_unresolved()
        )
        if unresolved_intents:
            return self._finish(
                ExecutionResult(
                    request=durable_request,
                    outcome=ExecutionOutcome.BLOCKED,
                    message=(
                        "Another durable order intent remains unresolved; "
                        "reconciliation is required before new execution."
                    ),
                )
            )

        now = self._now()
        intent = OrderIntent(
            intent_id=intent_id,
            strategy_name=strategy_name,
            symbol=request.symbol,
            timeframe_minutes=timeframe_minutes,
            signal_bar_end=signal_bar_end,
            action=action,
            side=request.side,
            requested_quantity=request.quantity,
            client_order_id=durable_client_id,
            position_generation_id=(
                position_generation_id
            ),
            lifecycle_state=OrderLifecycleState.CREATED,
            created_at=now,
            updated_at=now,
        )
        self._order_state_store.save(intent)
        self._emit("order_intent_created", intent)
        try:
            apply_confirmed_intent_to_position(
                intent,
                self._position_state_store,
                checked_at=now,
            )
            if request.side is OrderSide.BUY:
                self._emit(
                    "position_generation_created",
                    intent,
                )
        except Exception as exc:
            blocked = replace(
                intent,
                lifecycle_state=(
                    OrderLifecycleState.RECONCILIATION_REQUIRED
                ),
                updated_at=self._now(),
                last_error_type="position_persistence_failure",
                last_error_message=(
                    "Position ownership could not be persisted "
                    "before submission."
                ),
            )
            self._order_state_store.save(blocked)
            self._emit(
                "order_reconciliation_required",
                blocked,
                message=type(exc).__name__,
            )
            return self._result_for_intent(
                request=durable_request,
                intent=blocked,
                order=None,
                poll_count=0,
                newly_filled_quantity=0.0,
            )

        intent = replace(
            intent,
            lifecycle_state=OrderLifecycleState.SUBMITTING,
            updated_at=self._now(),
        )
        self._order_state_store.save(intent)
        self._emit("order_submission_started", intent)

        try:
            order = self._broker.submit_market_order(
                durable_request
            )
        except BrokerExecutionError as exc:
            return self._recover_submission_error(
                intent=intent,
                request=durable_request,
                error=exc,
            )

        intent, newly_filled = self._persist_broker_state(
            intent,
            order,
        )
        self._emit("order_submission_returned", intent)
        total_newly_filled = newly_filled

        if intent.lifecycle_state.is_terminal or intent.lifecycle_state is (
            OrderLifecycleState.RECONCILIATION_REQUIRED
        ):
            return self._result_for_intent(
                request=durable_request,
                intent=intent,
                order=order,
                poll_count=0,
                newly_filled_quantity=total_newly_filled,
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
            try:
                latest_order = self._broker.get_order(
                    order.order_id
                )
            except BrokerExecutionError as exc:
                uncertain = replace(
                    intent,
                    lifecycle_state=(
                        OrderLifecycleState
                        .RECONCILIATION_REQUIRED
                    ),
                    updated_at=self._now(),
                    last_error_type=exc.kind.value,
                    last_error_message=str(exc),
                )
                self._order_state_store.save(uncertain)
                self._emit(
                    "order_reconciliation_required",
                    uncertain,
                )
                return self._result_for_intent(
                    request=durable_request,
                    intent=uncertain,
                    order=latest_order,
                    poll_count=poll_count,
                    newly_filled_quantity=(
                        total_newly_filled
                    ),
                )

            intent, newly_filled = self._persist_broker_state(
                intent,
                latest_order,
            )
            total_newly_filled += newly_filled
            if (
                intent.lifecycle_state.is_terminal
                or intent.lifecycle_state
                is OrderLifecycleState.RECONCILIATION_REQUIRED
            ):
                return self._result_for_intent(
                    request=durable_request,
                    intent=intent,
                    order=latest_order,
                    poll_count=poll_count,
                    newly_filled_quantity=(
                        total_newly_filled
                    ),
                )

        cancellation_requested = False
        if self._settings.cancel_on_timeout:
            intent = replace(
                intent,
                cancellation_requested_at=self._now(),
                updated_at=self._now(),
            )
            self._order_state_store.save(intent)
            self._emit(
                "order_cancellation_requested",
                intent,
            )
            try:
                self._broker.cancel_order(
                    latest_order.order_id
                )
                cancellation_requested = True
            except BrokerExecutionError as exc:
                uncertain = replace(
                    intent,
                    lifecycle_state=(
                        OrderLifecycleState
                        .RECONCILIATION_REQUIRED
                    ),
                    updated_at=self._now(),
                    last_error_type=exc.kind.value,
                    last_error_message=str(exc),
                )
                self._order_state_store.save(uncertain)
                return self._result_for_intent(
                    request=durable_request,
                    intent=uncertain,
                    order=latest_order,
                    poll_count=(
                        self._settings.max_poll_attempts
                    ),
                    newly_filled_quantity=(
                        total_newly_filled
                    ),
                    cancellation_requested=False,
                )

            confirmation_attempts = math.ceil(
                self._settings
                .cancellation_confirmation_timeout_seconds
                / self._settings
                .cancellation_confirmation_poll_seconds
            )
            for offset in range(1, confirmation_attempts + 1):
                self._sleeper(
                    self._settings
                    .cancellation_confirmation_poll_seconds
                )
                try:
                    latest_order = self._broker.get_order(
                        latest_order.order_id
                    )
                except BrokerExecutionError:
                    break
                intent, newly_filled = (
                    self._persist_broker_state(
                        intent,
                        latest_order,
                    )
                )
                total_newly_filled += newly_filled
                if (
                    intent.lifecycle_state.is_terminal
                    or intent.lifecycle_state
                    is OrderLifecycleState
                    .RECONCILIATION_REQUIRED
                ):
                    return self._result_for_intent(
                        request=durable_request,
                        intent=intent,
                        order=latest_order,
                        poll_count=(
                            self._settings.max_poll_attempts
                            + offset
                        ),
                        newly_filled_quantity=(
                            total_newly_filled
                        ),
                        cancellation_requested=True,
                    )

        uncertain = replace(
            intent,
            lifecycle_state=(
                OrderLifecycleState.RECONCILIATION_REQUIRED
            ),
            updated_at=self._now(),
            last_error_type="cancellation_unconfirmed",
            last_error_message=(
                "Final broker status could not be confirmed."
            ),
        )
        self._order_state_store.save(uncertain)
        self._emit(
            "order_reconciliation_required",
            uncertain,
        )
        return self._result_for_intent(
            request=durable_request,
            intent=uncertain,
            order=latest_order,
            poll_count=self._settings.max_poll_attempts,
            newly_filled_quantity=total_newly_filled,
            cancellation_requested=cancellation_requested,
        )

    def get_account(self) -> AccountSnapshot:
        return self._broker.get_account()

    def get_clock(self) -> MarketClockSnapshot:
        return self._broker.get_clock()

    def list_open_orders(self) -> list[BrokerOrder]:
        return self._broker.list_open_orders()

    def list_positions(self) -> list[PositionSnapshot]:
        return self._broker.list_positions()

    def find_order_by_client_id(
        self,
        client_order_id: str,
    ) -> BrokerOrder | None:
        return self._broker.find_order_by_client_id(
            client_order_id
        )
