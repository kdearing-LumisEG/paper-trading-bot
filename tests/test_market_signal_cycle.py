"""Tests for the one-shot market-signal cycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from trading_bot.backtest.risk_manager import (
    RiskManager,
)
from trading_bot.broker.models import (
    MarketClockSnapshot,
)
from trading_bot.execution.signal_models import (
    SignalHandlingOutcome,
    SignalHandlingResult,
    StrategySignal,
    StrategySignalEvent,
)
from trading_bot.runtime.cycle import (
    DUPLICATE_BAR_REASON,
    INSUFFICIENT_BARS_REASON,
    MARKET_CLOSED_REASON,
    SESSION_FLATTEN_REASON,
    STALE_BAR_REASON,
    MarketSignalCycle,
    MarketSignalCycleOutcome,
    MarketSignalCycleSettings,
)
from trading_bot.runtime.signal_state import (
    JsonSignalStateStore,
    NullSignalStateStore,
)


class FakeBarSource:
    def __init__(
        self,
        frame: pd.DataFrame,
    ) -> None:
        self.frame = frame
        self.fetch_count = 0

    def fetch_bars(
        self,
        *,
        symbol: str,
        timeframe_minutes: int,
        start: datetime,
        end: datetime,
        data_feed: str,
    ) -> pd.DataFrame:
        del (
            symbol,
            timeframe_minutes,
            start,
            end,
            data_feed,
        )

        self.fetch_count += 1
        return self.frame.copy(deep=True)


@dataclass
class FakeClockSource:
    clock: MarketClockSnapshot

    def get_clock(
        self,
    ) -> MarketClockSnapshot:
        return self.clock


class RecordingSignalHandler:
    def __init__(self) -> None:
        self.events: list[
            StrategySignalEvent
        ] = []

    def handle(
        self,
        event: StrategySignalEvent,
    ) -> SignalHandlingResult:
        self.events.append(event)

        return SignalHandlingResult(
            event=event,
            outcome=(
                SignalHandlingOutcome.NO_ACTION
            ),
            reason="fake",
            position_quantity_before=0.0,
            risk_snapshot=(
                RiskManager().snapshot(
                    event.signal_time
                )
            ),
        )


def clock(
    *,
    timestamp: str = "2026-01-02T15:31:00Z",
    is_open: bool = True,
    next_close: str = "2026-01-02T21:00:00Z",
) -> MarketClockSnapshot:
    return MarketClockSnapshot(
        timestamp=pd.Timestamp(
            timestamp
        ).to_pydatetime(),
        is_open=is_open,
        next_open=pd.Timestamp(
            "2026-01-05T14:30:00Z"
        ).to_pydatetime(),
        next_close=pd.Timestamp(
            next_close
        ).to_pydatetime(),
    )


def bars(
    timestamps: list[str],
    closes: list[float],
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["SPY"] * len(
                timestamps
            ),
            "timestamp": pd.to_datetime(
                timestamps,
                utc=True,
            ),
            "open": closes,
            "high": [
                close + 0.5
                for close in closes
            ],
            "low": [
                close - 0.5
                for close in closes
            ],
            "close": closes,
            "volume": [1000] * len(
                timestamps
            ),
        }
    )


def crossover_frame() -> pd.DataFrame:
    return bars(
        [
            "2026-01-02T14:30:00Z",
            "2026-01-02T14:45:00Z",
            "2026-01-02T15:00:00Z",
            "2026-01-02T15:15:00Z",
            "2026-01-02T15:30:00Z",
        ],
        [
            10.0,
            9.0,
            8.0,
            12.0,
            13.0,
        ],
    )


def settings() -> MarketSignalCycleSettings:
    return MarketSignalCycleSettings(
        strategy_name="ema_2_3",
        symbol="SPY",
        timeframe_minutes=15,
        fast_ema=2,
        slow_ema=3,
        entry_quantity=1,
        data_feed="iex",
        lookback_calendar_days=5,
        bar_staleness_grace_seconds=120.0,
        flatten_minutes_before_close=15,
    )


def make_cycle(
    *,
    frame: pd.DataFrame,
    market_clock: MarketClockSnapshot | None = None,
    state_store=None,
) -> tuple[
    MarketSignalCycle,
    FakeBarSource,
    RecordingSignalHandler,
]:
    source = FakeBarSource(frame)
    handler = RecordingSignalHandler()

    cycle = MarketSignalCycle(
        bar_source=source,
        clock_source=FakeClockSource(
            market_clock
            if market_clock is not None
            else clock()
        ),
        signal_handler=handler,
        settings=settings(),
        signal_state_store=(
            state_store
            if state_store is not None
            else NullSignalStateStore()
        ),
    )

    return cycle, source, handler


def test_closed_market_blocks_before_fetch() -> None:
    closed_clock = clock(
        timestamp="2026-01-02T22:00:00Z",
        is_open=False,
        next_close="2026-01-05T21:00:00Z",
    )

    cycle, source, handler = make_cycle(
        frame=crossover_frame(),
        market_clock=closed_clock,
    )

    result = cycle.run()

    assert result.outcome is (
        MarketSignalCycleOutcome.BLOCKED
    )
    assert result.reason == MARKET_CLOSED_REASON
    assert source.fetch_count == 0
    assert handler.events == []


def test_incomplete_bar_is_discarded() -> None:
    cycle, _, handler = make_cycle(
        frame=crossover_frame()
    )

    result = cycle.run()

    assert result.outcome is (
        MarketSignalCycleOutcome.HANDLED
    )
    assert (
        result.discarded_incomplete_bar_count
        == 1
    )
    assert result.completed_bar_count == 4

    assert handler.events[
        0
    ].signal is StrategySignal.ENTER_LONG

    assert handler.events[
        0
    ].signal_time == datetime(
        2026,
        1,
        2,
        15,
        30,
        tzinfo=timezone.utc,
    )


def test_stale_latest_bar_is_blocked() -> None:
    stale_clock = clock(
        timestamp="2026-01-02T16:10:00Z"
    )

    cycle, _, handler = make_cycle(
        frame=crossover_frame().iloc[
            :4
        ].copy(),
        market_clock=stale_clock,
    )

    result = cycle.run()

    assert result.outcome is (
        MarketSignalCycleOutcome.BLOCKED
    )
    assert result.reason == STALE_BAR_REASON
    assert handler.events == []


def test_insufficient_bars_are_blocked() -> None:
    cycle, _, handler = make_cycle(
        frame=crossover_frame().iloc[
            :3
        ].copy()
    )

    result = cycle.run()

    assert result.reason == (
        INSUFFICIENT_BARS_REASON
    )
    assert handler.events == []


def test_processed_bar_is_not_handled_twice(
    tmp_path: Path,
) -> None:
    store = JsonSignalStateStore(
        tmp_path / "state.json"
    )

    first_cycle, _, first_handler = make_cycle(
        frame=crossover_frame(),
        state_store=store,
    )

    first = first_cycle.run()

    second_cycle, _, second_handler = make_cycle(
        frame=crossover_frame(),
        state_store=store,
    )

    second = second_cycle.run()

    assert first.outcome is (
        MarketSignalCycleOutcome.HANDLED
    )
    assert len(first_handler.events) == 1

    assert second.outcome is (
        MarketSignalCycleOutcome.DUPLICATE
    )
    assert second.reason == (
        DUPLICATE_BAR_REASON
    )
    assert second_handler.events == []


def test_force_reprocesses_latest_bar(
    tmp_path: Path,
) -> None:
    store = JsonSignalStateStore(
        tmp_path / "state.json"
    )

    first_cycle, _, _ = make_cycle(
        frame=crossover_frame(),
        state_store=store,
    )

    first_cycle.run()

    second_cycle, _, handler = make_cycle(
        frame=crossover_frame(),
        state_store=store,
    )

    result = second_cycle.run(
        force=True
    )

    assert result.outcome is (
        MarketSignalCycleOutcome.HANDLED
    )
    assert len(handler.events) == 1


def test_near_close_forces_exit_signal() -> None:
    frame = bars(
        [
            "2026-01-02T19:45:00Z",
            "2026-01-02T20:00:00Z",
            "2026-01-02T20:15:00Z",
            "2026-01-02T20:30:00Z",
            "2026-01-02T20:45:00Z",
        ],
        [
            10.0,
            9.0,
            8.0,
            12.0,
            13.0,
        ],
    )

    near_close = clock(
        timestamp="2026-01-02T20:46:00Z",
        next_close="2026-01-02T21:00:00Z",
    )

    cycle, _, handler = make_cycle(
        frame=frame,
        market_clock=near_close,
    )

    result = cycle.run()

    assert result.reason == (
        SESSION_FLATTEN_REASON
    )
    assert result.forced_session_flatten
    assert handler.events[
        0
    ].signal is StrategySignal.EXIT_LONG
    assert result.generated_signal is (
        StrategySignal.ENTER_LONG
    )
