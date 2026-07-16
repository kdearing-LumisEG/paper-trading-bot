"""Tests for deterministic strategy client-order IDs."""

from datetime import datetime, timezone

from trading_bot.broker.models import OrderSide
from trading_bot.execution.client_ids import (
    build_signal_client_order_id,
)
from trading_bot.execution.signal_models import (
    StrategySignal,
    StrategySignalEvent,
)


def make_event(
    strategy_name: str = "ema_crossover_9_21",
) -> StrategySignalEvent:
    return StrategySignalEvent(
        strategy_name=strategy_name,
        symbol="SPY",
        signal=StrategySignal.ENTER_LONG,
        signal_time=datetime(
            2026,
            1,
            2,
            15,
            0,
            tzinfo=timezone.utc,
        ),
    )


def test_client_order_id_is_deterministic() -> None:
    first = build_signal_client_order_id(
        make_event(),
        OrderSide.BUY,
    )

    second = build_signal_client_order_id(
        make_event(),
        OrderSide.BUY,
    )

    assert first == second
    assert "SPY" in first
    assert "buy" in first


def test_side_changes_client_order_id() -> None:
    event = make_event()

    buy_id = build_signal_client_order_id(
        event,
        OrderSide.BUY,
    )

    sell_id = build_signal_client_order_id(
        event,
        OrderSide.SELL,
    )

    assert buy_id != sell_id


def test_long_client_order_id_is_hashed_to_limit() -> None:
    result = build_signal_client_order_id(
        make_event(
            strategy_name=(
                "very_long_strategy_name_"
                "with_many_components_12345"
            )
        ),
        OrderSide.BUY,
    )

    assert len(result) <= 48
