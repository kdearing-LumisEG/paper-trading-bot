"""Deterministic client-order identifiers for strategy signals."""

from __future__ import annotations

from datetime import timezone
import hashlib
import re

from trading_bot.broker.models import (
    OrderSide,
)
from trading_bot.execution.signal_models import (
    StrategySignalEvent,
)


_UNSUPPORTED_ID_CHARACTERS = re.compile(
    r"[^A-Za-z0-9._:-]+"
)


def _normalized_identity_part(value: str) -> str:
    result = _UNSUPPORTED_ID_CHARACTERS.sub(
        "-",
        value.strip(),
    ).strip("-._:")
    return result or "unknown"


def build_order_intent_identity(
    *,
    strategy_name: str,
    symbol: str,
    timeframe_minutes: int,
    signal_bar_end,
    action: str,
    position_generation_id: str,
) -> str:
    """Return a stable full identity for one logical strategy action."""

    timestamp = signal_bar_end.astimezone(
        timezone.utc
    ).isoformat()
    raw_value = "|".join(
        (
            strategy_name.strip(),
            symbol.strip().upper(),
            str(timeframe_minutes),
            timestamp,
            action.strip(),
            position_generation_id.strip(),
        )
    )
    return hashlib.sha256(
        raw_value.encode("utf-8")
    ).hexdigest()


def build_position_generation_id(
    *,
    strategy_name: str,
    symbol: str,
    timeframe_minutes: int,
    signal_bar_end,
) -> str:
    """Return the stable generation identifier for one entry action."""

    identity = build_order_intent_identity(
        strategy_name=strategy_name,
        symbol=symbol,
        timeframe_minutes=timeframe_minutes,
        signal_bar_end=signal_bar_end,
        action="position_generation",
        position_generation_id="entry",
    )
    return f"pg-{identity[:24]}"


def build_order_client_order_id(
    *,
    intent_id: str,
    strategy_name: str,
    symbol: str,
    side: OrderSide,
    action: str,
) -> str:
    """Return an Alpaca-compatible ID derived from durable intent identity."""

    prefix = "-".join(
        (
            _normalized_identity_part(strategy_name)[:10],
            _normalized_identity_part(symbol)[:6],
            side.value,
            _normalized_identity_part(action)[:8],
        )
    )
    digest = hashlib.sha256(
        intent_id.encode("utf-8")
    ).hexdigest()[:12]
    available = 48 - len(digest) - 1
    prefix = prefix[:available].rstrip("-._:")
    return f"{prefix}-{digest}"


def build_signal_client_order_id(
    event: StrategySignalEvent,
    side: OrderSide,
) -> str:
    """Return a stable Alpaca-compatible ID for one signal."""

    timestamp = event.signal_time.astimezone(
        timezone.utc
    ).strftime(
        "%Y%m%dT%H%M%SZ"
    )

    strategy_name = (
        _UNSUPPORTED_ID_CHARACTERS.sub(
            "-",
            event.strategy_name,
        )
        .strip("-._:")
    )

    raw_value = (
        f"{strategy_name}-"
        f"{event.symbol}-"
        f"{side.value}-"
        f"{timestamp}"
    )

    if len(raw_value) <= 48:
        return raw_value

    digest = hashlib.sha256(
        raw_value.encode("utf-8")
    ).hexdigest()[:10]

    prefix_length = 48 - len(digest) - 1

    prefix = raw_value[
        :prefix_length
    ].rstrip("-._:")

    return f"{prefix}-{digest}"
