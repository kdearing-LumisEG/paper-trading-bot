"""One-shot market-data to paper-execution strategy cycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import math
from typing import Protocol
from zoneinfo import ZoneInfo

import pandas as pd

from trading_bot.broker.models import (
    MarketClockSnapshot,
)
from trading_bot.data.validation import (
    filter_regular_session_bars,
    validate_bars,
)
from trading_bot.execution.signal_models import (
    SignalHandlingOutcome,
    SignalHandlingResult,
    StrategySignal,
    StrategySignalEvent,
)
from trading_bot.runtime.market_data import (
    RecentBarSource,
)
from trading_bot.runtime.signal_state import (
    NullSignalStateStore,
    SignalStateStore,
)
from trading_bot.strategies.indicators import (
    add_ema_indicators,
)
from trading_bot.strategies.signals import (
    add_crossover_signals,
)


MARKET_CLOSED_REASON = "market_closed"
NO_BARS_REASON = "no_bars"
NO_COMPLETED_BARS_REASON = "no_completed_bars"
LATEST_BAR_WRONG_SESSION_REASON = (
    "latest_bar_not_current_session"
)
STALE_BAR_REASON = "stale_bar"
INSUFFICIENT_BARS_REASON = "insufficient_bars"
DUPLICATE_BAR_REASON = "bar_already_processed"
SIGNAL_HANDLED_REASON = "signal_handled"
SESSION_FLATTEN_REASON = "session_flatten"


class MarketSignalCycleOutcome(str, Enum):
    """High-level outcome of one market-signal cycle."""

    BLOCKED = "blocked"
    DUPLICATE = "duplicate"
    HANDLED = "handled"


@dataclass(frozen=True)
class MarketSignalCycleSettings:
    """Validated settings required by one strategy cycle."""

    strategy_name: str
    symbol: str
    timeframe_minutes: int
    fast_ema: int
    slow_ema: int
    entry_quantity: int
    data_feed: str
    lookback_calendar_days: int = 14
    bar_staleness_grace_seconds: float = 120.0
    flatten_minutes_before_close: int = 15

    def __post_init__(self) -> None:
        strategy_name = self.strategy_name.strip()
        symbol = self.symbol.strip().upper()
        data_feed = self.data_feed.strip().lower()

        if not strategy_name:
            raise ValueError(
                "strategy_name cannot be empty."
            )

        if not symbol:
            raise ValueError(
                "symbol cannot be empty."
            )

        for field_name, value in {
            "timeframe_minutes": self.timeframe_minutes,
            "fast_ema": self.fast_ema,
            "slow_ema": self.slow_ema,
            "entry_quantity": self.entry_quantity,
            "lookback_calendar_days": (
                self.lookback_calendar_days
            ),
            "flatten_minutes_before_close": (
                self.flatten_minutes_before_close
            ),
        }.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
            ):
                raise ValueError(
                    f"{field_name} must be a positive integer."
                )

        if self.fast_ema >= self.slow_ema:
            raise ValueError(
                "fast_ema must be smaller than slow_ema."
            )

        if data_feed not in {
            "iex",
            "sip",
        }:
            raise ValueError(
                "data_feed must be either 'iex' or 'sip'."
            )

        if (
            not math.isfinite(
                self.bar_staleness_grace_seconds
            )
            or self.bar_staleness_grace_seconds < 0
        ):
            raise ValueError(
                "bar_staleness_grace_seconds must be "
                "finite and nonnegative."
            )

        object.__setattr__(
            self,
            "strategy_name",
            strategy_name,
        )
        object.__setattr__(
            self,
            "symbol",
            symbol,
        )
        object.__setattr__(
            self,
            "data_feed",
            data_feed,
        )


@dataclass(frozen=True)
class MarketSignalCycleResult:
    """Auditable result of one market-signal cycle."""

    outcome: MarketSignalCycleOutcome
    reason: str
    market_clock: MarketClockSnapshot
    fetched_bar_count: int = 0
    completed_bar_count: int = 0
    discarded_incomplete_bar_count: int = 0
    latest_bar_timestamp: datetime | None = None
    latest_bar_end: datetime | None = None
    generated_signal: StrategySignal | None = None
    forced_session_flatten: bool = False
    signal_event: StrategySignalEvent | None = None
    signal_result: SignalHandlingResult | None = None


class MarketClockSource(Protocol):
    """Source of the current regular-market clock."""

    def get_clock(
        self,
    ) -> MarketClockSnapshot:
        """Return the current regular-market clock."""


class SignalHandler(Protocol):
    """Handler for one deterministic strategy signal."""

    def handle(
        self,
        event: StrategySignalEvent,
    ) -> SignalHandlingResult:
        """Handle one signal event."""


def _as_utc_datetime(
    value: object,
) -> datetime:
    timestamp = pd.Timestamp(value)

    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(
            "UTC"
        )
    else:
        timestamp = timestamp.tz_convert(
            "UTC"
        )

    return timestamp.to_pydatetime()


def _exchange_date(
    value: datetime,
) -> object:
    return value.astimezone(
        ZoneInfo("America/New_York")
    ).date()


class MarketSignalCycle:
    """Evaluate the latest completed bar and handle one signal."""

    def __init__(
        self,
        *,
        bar_source: RecentBarSource,
        clock_source: MarketClockSource,
        signal_handler: SignalHandler,
        settings: MarketSignalCycleSettings,
        signal_state_store: SignalStateStore | None = None,
    ) -> None:
        self._bar_source = bar_source
        self._clock_source = clock_source
        self._signal_handler = signal_handler
        self._settings = settings
        self._signal_state_store = (
            signal_state_store
            if signal_state_store is not None
            else NullSignalStateStore()
        )

    def _blocked(
        self,
        *,
        clock: MarketClockSnapshot,
        reason: str,
        fetched_bar_count: int = 0,
        completed_bar_count: int = 0,
        discarded_incomplete_bar_count: int = 0,
        latest_bar_timestamp: datetime | None = None,
        latest_bar_end: datetime | None = None,
    ) -> MarketSignalCycleResult:
        return MarketSignalCycleResult(
            outcome=(
                MarketSignalCycleOutcome.BLOCKED
            ),
            reason=reason,
            market_clock=clock,
            fetched_bar_count=fetched_bar_count,
            completed_bar_count=completed_bar_count,
            discarded_incomplete_bar_count=(
                discarded_incomplete_bar_count
            ),
            latest_bar_timestamp=(
                latest_bar_timestamp
            ),
            latest_bar_end=latest_bar_end,
        )

    def run(
        self,
        *,
        force: bool = False,
    ) -> MarketSignalCycleResult:
        """Run one safe, deterministic market-signal cycle."""

        clock = self._clock_source.get_clock()

        if not clock.is_open:
            return self._blocked(
                clock=clock,
                reason=MARKET_CLOSED_REASON,
            )

        settings = self._settings

        start = (
            clock.timestamp
            - timedelta(
                days=(
                    settings
                    .lookback_calendar_days
                )
            )
        )

        raw_bars = self._bar_source.fetch_bars(
            symbol=settings.symbol,
            timeframe_minutes=(
                settings.timeframe_minutes
            ),
            start=start,
            end=clock.timestamp,
            data_feed=settings.data_feed,
        )

        fetched_bar_count = len(raw_bars)

        if raw_bars.empty:
            return self._blocked(
                clock=clock,
                reason=NO_BARS_REASON,
            )

        validated = validate_bars(
            raw_bars,
            expected_symbol=settings.symbol,
            timeframe_minutes=(
                settings.timeframe_minutes
            ),
        )

        regular_bars = (
            filter_regular_session_bars(
                validated
            )
        )

        bar_duration = timedelta(
            minutes=settings.timeframe_minutes
        )

        bar_ends = (
            regular_bars["timestamp"]
            + pd.Timedelta(
                minutes=(
                    settings
                    .timeframe_minutes
                )
            )
        )

        completed_mask = (
            bar_ends
            <= pd.Timestamp(
                clock.timestamp
            )
        )

        completed = (
            regular_bars.loc[
                completed_mask
            ]
            .reset_index(drop=True)
        )

        discarded_incomplete_bar_count = int(
            (~completed_mask).sum()
        )

        completed_bar_count = len(
            completed
        )

        if completed.empty:
            return self._blocked(
                clock=clock,
                reason=NO_COMPLETED_BARS_REASON,
                fetched_bar_count=(
                    fetched_bar_count
                ),
                completed_bar_count=0,
                discarded_incomplete_bar_count=(
                    discarded_incomplete_bar_count
                ),
            )

        latest_bar_timestamp = (
            _as_utc_datetime(
                completed[
                    "timestamp"
                ].iloc[-1]
            )
        )

        latest_bar_end = (
            latest_bar_timestamp
            + bar_duration
        )

        if (
            _exchange_date(
                latest_bar_timestamp
            )
            != _exchange_date(
                clock.timestamp
            )
        ):
            return self._blocked(
                clock=clock,
                reason=(
                    LATEST_BAR_WRONG_SESSION_REASON
                ),
                fetched_bar_count=(
                    fetched_bar_count
                ),
                completed_bar_count=(
                    completed_bar_count
                ),
                discarded_incomplete_bar_count=(
                    discarded_incomplete_bar_count
                ),
                latest_bar_timestamp=(
                    latest_bar_timestamp
                ),
                latest_bar_end=latest_bar_end,
            )

        maximum_bar_age = (
            bar_duration
            + timedelta(
                seconds=(
                    settings
                    .bar_staleness_grace_seconds
                )
            )
        )

        latest_bar_age = (
            clock.timestamp
            - latest_bar_end
        )

        if (
            latest_bar_age < timedelta(0)
            or latest_bar_age
            > maximum_bar_age
        ):
            return self._blocked(
                clock=clock,
                reason=STALE_BAR_REASON,
                fetched_bar_count=(
                    fetched_bar_count
                ),
                completed_bar_count=(
                    completed_bar_count
                ),
                discarded_incomplete_bar_count=(
                    discarded_incomplete_bar_count
                ),
                latest_bar_timestamp=(
                    latest_bar_timestamp
                ),
                latest_bar_end=latest_bar_end,
            )

        minimum_bar_count = (
            settings.slow_ema + 1
        )

        if (
            completed_bar_count
            < minimum_bar_count
        ):
            return self._blocked(
                clock=clock,
                reason=INSUFFICIENT_BARS_REASON,
                fetched_bar_count=(
                    fetched_bar_count
                ),
                completed_bar_count=(
                    completed_bar_count
                ),
                discarded_incomplete_bar_count=(
                    discarded_incomplete_bar_count
                ),
                latest_bar_timestamp=(
                    latest_bar_timestamp
                ),
                latest_bar_end=latest_bar_end,
            )

        indicator_bars = add_ema_indicators(
            completed,
            fast_period=settings.fast_ema,
            slow_period=settings.slow_ema,
        )

        strategy_bars = (
            add_crossover_signals(
                indicator_bars
            )
        )

        generated_signal = StrategySignal(
            strategy_bars[
                "signal"
            ].iloc[-1]
        )

        time_to_close = (
            clock.next_close
            - clock.timestamp
        )

        forced_session_flatten = (
            timedelta(0)
            < time_to_close
            <= timedelta(
                minutes=(
                    settings
                    .flatten_minutes_before_close
                )
            )
        )

        signal = (
            StrategySignal.EXIT_LONG
            if forced_session_flatten
            else generated_signal
        )

        if (
            not force
            and not forced_session_flatten
            and self._signal_state_store
            .is_processed(
                strategy_name=(
                    settings.strategy_name
                ),
                symbol=settings.symbol,
                timeframe_minutes=(
                    settings
                    .timeframe_minutes
                ),
                bar_end=latest_bar_end,
            )
        ):
            return MarketSignalCycleResult(
                outcome=(
                    MarketSignalCycleOutcome
                    .DUPLICATE
                ),
                reason=DUPLICATE_BAR_REASON,
                market_clock=clock,
                fetched_bar_count=(
                    fetched_bar_count
                ),
                completed_bar_count=(
                    completed_bar_count
                ),
                discarded_incomplete_bar_count=(
                    discarded_incomplete_bar_count
                ),
                latest_bar_timestamp=(
                    latest_bar_timestamp
                ),
                latest_bar_end=latest_bar_end,
                generated_signal=(
                    generated_signal
                ),
                forced_session_flatten=(
                    forced_session_flatten
                ),
            )

        event = StrategySignalEvent(
            strategy_name=(
                settings.strategy_name
            ),
            symbol=settings.symbol,
            signal=signal,
            signal_time=latest_bar_end,
            entry_quantity=(
                settings.entry_quantity
            ),
            timeframe_minutes=(
                settings.timeframe_minutes
            ),
            reference_price=float(
                completed["close"].iloc[-1]
            ),
            action=(
                "session_flatten"
                if forced_session_flatten
                else signal.value
            ),
            identity_time=(
                clock.next_close
                if forced_session_flatten
                else latest_bar_end
            ),
        )

        signal_result = (
            self._signal_handler.handle(
                event
            )
        )

        action_captured = (
            signal_result.outcome is not SignalHandlingOutcome.BLOCKED
            or (
                signal_result.execution_result is not None
                and signal_result.execution_result.intent_id
                is not None
            )
        )
        if action_captured:
            self._signal_state_store.mark_processed(
                strategy_name=(
                    settings.strategy_name
                ),
                symbol=settings.symbol,
                timeframe_minutes=(
                    settings.timeframe_minutes
                ),
                bar_end=latest_bar_end,
                signal=signal.value,
                handled_at=clock.timestamp,
            )

        return MarketSignalCycleResult(
            outcome=(
                MarketSignalCycleOutcome.HANDLED
            ),
            reason=(
                SESSION_FLATTEN_REASON
                if forced_session_flatten
                else SIGNAL_HANDLED_REASON
            ),
            market_clock=clock,
            fetched_bar_count=(
                fetched_bar_count
            ),
            completed_bar_count=(
                completed_bar_count
            ),
            discarded_incomplete_bar_count=(
                discarded_incomplete_bar_count
            ),
            latest_bar_timestamp=(
                latest_bar_timestamp
            ),
            latest_bar_end=latest_bar_end,
            generated_signal=(
                generated_signal
            ),
            forced_session_flatten=(
                forced_session_flatten
            ),
            signal_event=event,
            signal_result=signal_result,
        )
