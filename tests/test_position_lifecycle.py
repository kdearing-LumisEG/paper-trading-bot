"""Position-generation transitions from broker-confirmed order facts."""

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from trading_bot.broker.models import OrderSide
from trading_bot.execution.order_state import OrderIntent, OrderLifecycleState
from trading_bot.execution.position_state import (
    JsonPositionStateStore,
    PositionPhase,
    TrackedPosition,
)
from trading_bot.execution.service import apply_confirmed_intent_to_position


NOW = datetime(2026, 7, 21, 20, 0, tzinfo=timezone.utc)


def intent(side: OrderSide) -> OrderIntent:
    return OrderIntent(
        intent_id=f"{side.value}-intent",
        strategy_name="ema_9_21",
        symbol="SPY",
        timeframe_minutes=15,
        signal_bar_end=NOW,
        action="enter_long" if side is OrderSide.BUY else "exit_long",
        side=side,
        requested_quantity=2,
        client_order_id=f"{side.value}-client",
        position_generation_id="pg-owned",
        lifecycle_state=OrderLifecycleState.ACCEPTED,
        created_at=NOW,
        updated_at=NOW,
        broker_order_id=f"{side.value}-broker",
    )


def test_entry_partial_full_and_terminal_zero_fill(tmp_path: Path) -> None:
    store = JsonPositionStateStore(tmp_path / "positions.json")
    entry = intent(OrderSide.BUY)

    pending = apply_confirmed_intent_to_position(entry, store, checked_at=NOW)
    partial = apply_confirmed_intent_to_position(
        replace(
            entry,
            lifecycle_state=OrderLifecycleState.PARTIALLY_FILLED,
            filled_quantity=1,
            average_fill_price=500,
        ),
        store,
        checked_at=NOW,
    )
    full = apply_confirmed_intent_to_position(
        replace(
            entry,
            lifecycle_state=OrderLifecycleState.FILLED,
            filled_quantity=2,
            average_fill_price=501,
        ),
        store,
        checked_at=NOW,
    )

    assert pending.phase is PositionPhase.ENTRY_PENDING
    assert partial.quantity == pytest.approx(1)
    assert full.quantity == pytest.approx(2)
    assert full.entry_intent_id == entry.intent_id
    assert full.entry_broker_order_id == "buy-broker"

    zero_store = JsonPositionStateStore(tmp_path / "zero.json")
    failed = apply_confirmed_intent_to_position(
        replace(entry, lifecycle_state=OrderLifecycleState.REJECTED),
        zero_store,
        checked_at=NOW,
    )
    assert failed.phase is PositionPhase.FLAT
    assert failed.quantity == 0


def test_exit_partial_full_and_rejection_preserve_linkage(tmp_path: Path) -> None:
    store = JsonPositionStateStore(tmp_path / "positions.json")
    store.save(
        TrackedPosition(
            symbol="SPY",
            strategy_name="ema_9_21",
            position_generation_id="pg-owned",
            phase=PositionPhase.OPEN,
            quantity=2,
            average_entry_price=500,
            updated_at=NOW,
            entry_intent_id="buy-intent",
            entry_client_order_id="buy-client",
            entry_broker_order_id="buy-broker",
        )
    )
    exit_intent = intent(OrderSide.SELL)

    pending = apply_confirmed_intent_to_position(
        exit_intent,
        store,
        checked_at=NOW,
    )
    partial = apply_confirmed_intent_to_position(
        replace(
            exit_intent,
            lifecycle_state=OrderLifecycleState.PARTIALLY_FILLED,
            filled_quantity=1,
            average_fill_price=510,
        ),
        store,
        checked_at=NOW,
    )
    full = apply_confirmed_intent_to_position(
        replace(
            exit_intent,
            lifecycle_state=OrderLifecycleState.FILLED,
            filled_quantity=2,
            average_fill_price=511,
        ),
        store,
        checked_at=NOW,
    )

    assert pending.phase is PositionPhase.EXIT_PENDING
    assert partial.phase is PositionPhase.OPEN
    assert partial.quantity == pytest.approx(1)
    assert full.phase is PositionPhase.FLAT
    assert full.entry_intent_id == "buy-intent"
    assert full.exit_intent_id == "sell-intent"

    rejection_store = JsonPositionStateStore(tmp_path / "rejection.json")
    rejection_store.save(
        replace(
            pending,
            phase=PositionPhase.OPEN,
            exit_intent_id=None,
            exit_client_order_id=None,
            exit_broker_order_id=None,
        )
    )
    rejected = apply_confirmed_intent_to_position(
        replace(exit_intent, lifecycle_state=OrderLifecycleState.REJECTED),
        rejection_store,
        checked_at=NOW,
    )
    assert rejected.phase is PositionPhase.OPEN
    assert rejected.quantity == pytest.approx(2)
