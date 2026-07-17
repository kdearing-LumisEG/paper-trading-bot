"""Tests for reconciliation configuration."""

from pathlib import Path

import pytest

from trading_bot.config import load_settings


def test_reconciliation_settings_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "strategy.yaml"

    config_path.write_text(
        """
symbol: SPY
timeframe_minutes: 15
data_feed: iex

strategy:
  fast_ema: 9
  slow_ema: 21

reconciliation:
  position_state_path: state/position.json
  report_log_path: logs/reconciliation.jsonl
  process_lock_path: state/runtime.lock
  average_price_tolerance: 0.05
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

    settings = load_settings(
        config_path=config_path,
        env_path=tmp_path / "missing.env",
    )

    reconciliation = settings.reconciliation

    assert reconciliation.position_state_path == Path(
        "state/position.json"
    )
    assert reconciliation.report_log_path == Path(
        "logs/reconciliation.jsonl"
    )
    assert reconciliation.process_lock_path == Path(
        "state/runtime.lock"
    )
    assert (
        reconciliation.average_price_tolerance
        == pytest.approx(0.05)
    )


def test_negative_price_tolerance_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "strategy.yaml"

    config_path.write_text(
        """
symbol: SPY
timeframe_minutes: 15
data_feed: iex
strategy:
  fast_ema: 9
  slow_ema: 21
reconciliation:
  average_price_tolerance: -0.01
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
        match="Configuration contains",
    ):
        load_settings(
            config_path=config_path,
            env_path=tmp_path / "missing.env",
        )
