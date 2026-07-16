"""Tests for strategy signal execution models."""

from datetime import datetime, timezone

import pytest

from trading_bot.execution.signal_models import (
    SignalModelError,
    StrategySignal,
    StrategySignalEvent,
)


def test_signal_event_normalizes_symbol_and_time() -> None:
    event = StrategySignalEvent(
        strategy_name="ema_9_21",
        symbol=" spy ",
        signal=StrategySignal.ENTER_LONG,
        signal_time=datetime(
            2026,
            1,
            2,
            15,
            0,
        ),
        entry_quantity=1,
    )

    assert event.symbol == "SPY"
    assert event.signal_time.tzinfo is timezone.utc


@pytest.mark.parametrize(
    "quantity",
    [
        0,
        -1,
        True,
        1.5,
    ],
)
def test_invalid_entry_quantity_fails(
    quantity: object,
) -> None:
    with pytest.raises(
        SignalModelError,
        match="positive integer",
    ):
        StrategySignalEvent(
            strategy_name="ema_9_21",
            symbol="SPY",
            signal=StrategySignal.ENTER_LONG,
            signal_time=datetime.now(
                timezone.utc
            ),
            entry_quantity=quantity,  # type: ignore[arg-type]
        )


def test_invalid_strategy_name_fails() -> None:
    with pytest.raises(
        SignalModelError,
        match="unsupported characters",
    ):
        StrategySignalEvent(
            strategy_name="ema strategy",
            symbol="SPY",
            signal=StrategySignal.HOLD,
            signal_time=datetime.now(
                timezone.utc
            ),
        )
