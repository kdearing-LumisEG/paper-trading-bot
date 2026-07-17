"""Tests for one-shot market-signal configuration."""

from pathlib import Path

import pytest

from trading_bot.config import (
    load_settings,
)


def write_config(
    path: Path,
    *,
    grace_seconds: str = "120.0",
) -> None:
    path.write_text(
        f"""
symbol: SPY
timeframe_minutes: 15
data_feed: iex

strategy:
  name: ema_crossover_9_21
  fast_ema: 9
  slow_ema: 21

market_signal:
  lookback_calendar_days: 10
  bar_staleness_grace_seconds: {grace_seconds}
  flatten_minutes_before_close: 15
  signal_state_path: logs/execution/market_state.json
""".strip(),
        encoding="utf-8",
    )


def test_market_signal_settings_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = (
        tmp_path / "strategy.yaml"
    )

    write_config(config_path)

    monkeypatch.setenv(
        "ALPACA_API_KEY",
        "test-key",
    )

    monkeypatch.setenv(
        "ALPACA_SECRET_KEY",
        "test-secret",
    )

    settings = load_settings(
        config_path=config_path,
        env_path=(
            tmp_path / "missing.env"
        ),
    )

    market = settings.market_signal

    assert market.lookback_calendar_days == 10

    assert (
        market.bar_staleness_grace_seconds
        == pytest.approx(120.0)
    )

    assert (
        market.flatten_minutes_before_close
        == 15
    )

    assert market.signal_state_path == Path(
        "logs/execution/market_state.json"
    )


def test_invalid_staleness_grace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = (
        tmp_path / "strategy.yaml"
    )

    write_config(
        config_path,
        grace_seconds="-1",
    )

    monkeypatch.setenv(
        "ALPACA_API_KEY",
        "test-key",
    )

    monkeypatch.setenv(
        "ALPACA_SECRET_KEY",
        "test-secret",
    )

    with pytest.raises(
        ValueError,
        match=(
            "Configuration contains "
            "missing or invalid values"
        ),
    ):
        load_settings(
            config_path=config_path,
            env_path=(
                tmp_path / "missing.env"
            ),
        )
