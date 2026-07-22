"""Tests for deterministic strategy client-order IDs."""

from datetime import datetime, timezone
import re

from trading_bot.broker.models import OrderSide
from trading_bot.execution.client_ids import (
    build_order_client_order_id,
    build_order_intent_identity,
    build_position_generation_id,
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


def test_durable_identity_includes_action_context() -> None:
    event = make_event()
    generation = build_position_generation_id(
        strategy_name=event.strategy_name,
        symbol=event.symbol,
        timeframe_minutes=15,
        signal_bar_end=event.signal_time,
    )
    base = build_order_intent_identity(
        strategy_name=event.strategy_name,
        symbol=event.symbol,
        timeframe_minutes=15,
        signal_bar_end=event.signal_time,
        action="exit_long",
        position_generation_id=generation,
    )

    assert base == build_order_intent_identity(
        strategy_name=event.strategy_name,
        symbol=event.symbol,
        timeframe_minutes=15,
        signal_bar_end=event.signal_time,
        action="exit_long",
        position_generation_id=generation,
    )
    assert base != build_order_intent_identity(
        strategy_name=event.strategy_name,
        symbol=event.symbol,
        timeframe_minutes=5,
        signal_bar_end=event.signal_time,
        action="exit_long",
        position_generation_id=generation,
    )
    assert base != build_order_intent_identity(
        strategy_name=event.strategy_name,
        symbol=event.symbol,
        timeframe_minutes=15,
        signal_bar_end=event.signal_time,
        action="exit_long",
        position_generation_id="different-generation",
    )
    assert base != build_order_intent_identity(
        strategy_name=event.strategy_name,
        symbol=event.symbol,
        timeframe_minutes=15,
        signal_bar_end=event.signal_time,
        action="session_flatten",
        position_generation_id=generation,
    )


def test_durable_client_id_is_safe_and_intent_specific() -> None:
    first = build_order_client_order_id(
        intent_id="a" * 64,
        strategy_name="very long strategy name / unsafe",
        symbol="SPY",
        side=OrderSide.SELL,
        action="session_flatten",
    )
    second = build_order_client_order_id(
        intent_id="b" * 64,
        strategy_name="very long strategy name / unsafe",
        symbol="SPY",
        side=OrderSide.SELL,
        action="session_flatten",
    )

    assert first != second
    assert first == build_order_client_order_id(
        intent_id="a" * 64,
        strategy_name="very long strategy name / unsafe",
        symbol="SPY",
        side=OrderSide.SELL,
        action="session_flatten",
    )
    assert len(first) <= 48
    assert re.fullmatch(r"[A-Za-z0-9._:-]+", first)
