"""Tests for signal-execution configuration."""

from pathlib import Path

import pytest

from trading_bot.config import (
    load_settings,
)


def write_config(
    path: Path,
    *,
    max_daily_loss: str = "25.0",
    max_trades: str = "3",
    max_losses: str = "2",
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

paper_execution:
  quantity: 1
  poll_interval_seconds: 1.0
  max_poll_attempts: 10
  max_daily_loss: {max_daily_loss}
  max_trades_per_session: {max_trades}
  max_consecutive_losses: {max_losses}
  order_log_path: logs/execution/orders.jsonl
  decision_log_path: logs/execution/decisions.jsonl
  risk_state_path: logs/execution/risk.json
""".strip(),
        encoding="utf-8",
    )


def test_signal_execution_settings_load(
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

    execution = settings.paper_execution

    assert settings.strategy.name == (
        "ema_crossover_9_21"
    )

    assert execution.quantity == 1
    assert execution.max_daily_loss == (
        pytest.approx(25.0)
    )
    assert execution.max_trades_per_session == 3
    assert execution.max_consecutive_losses == 2
    assert execution.risk_state_path == Path(
        "logs/execution/risk.json"
    )


def test_null_risk_limits_are_supported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = (
        tmp_path / "strategy.yaml"
    )

    write_config(
        config_path,
        max_daily_loss="null",
        max_trades="null",
        max_losses="null",
    )

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

    execution = settings.paper_execution

    assert execution.max_daily_loss is None
    assert execution.max_trades_per_session is None
    assert execution.max_consecutive_losses is None


def test_invalid_execution_quantity_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = (
        tmp_path / "strategy.yaml"
    )

    config_path.write_text(
        """
symbol: SPY
timeframe_minutes: 15
data_feed: iex
strategy:
  fast_ema: 9
  slow_ema: 21
paper_execution:
  quantity: 0
""".strip(),
        encoding="utf-8",
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
