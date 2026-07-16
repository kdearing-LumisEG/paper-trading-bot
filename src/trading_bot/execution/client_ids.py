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
