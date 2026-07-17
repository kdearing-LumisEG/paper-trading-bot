"""Tests for market-clock normalization."""

from datetime import datetime, timezone
from types import SimpleNamespace

from trading_bot.broker.alpaca_client import (
    AlpacaPaperBroker,
)


class FakeClockClient:
    def get_clock(self):
        return SimpleNamespace(
            timestamp=datetime(
                2026,
                1,
                2,
                15,
                0,
                tzinfo=timezone.utc,
            ),
            is_open=True,
            next_open=datetime(
                2026,
                1,
                5,
                14,
                30,
                tzinfo=timezone.utc,
            ),
            next_close=datetime(
                2026,
                1,
                2,
                21,
                0,
                tzinfo=timezone.utc,
            ),
        )


def test_alpaca_clock_is_normalized() -> None:
    broker = AlpacaPaperBroker(
        api_key="paper-key",
        secret_key="paper-secret",
        trading_client=FakeClockClient(),  # type: ignore[arg-type]
    )

    clock = broker.get_clock()

    assert clock.is_open is True
    assert clock.timestamp.tzinfo is timezone.utc
    assert clock.next_close == datetime(
        2026,
        1,
        2,
        21,
        0,
        tzinfo=timezone.utc,
    )
