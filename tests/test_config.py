"""Tests for application configuration."""

from pathlib import Path

import pytest

from trading_bot.config import load_settings


def write_config(
    path: Path,
    fast_ema: int = 9,
    slow_ema: int = 21,
) -> None:
    """Create a temporary YAML configuration for testing."""

    path.write_text(
        f"""
symbol: SPY
timeframe_minutes: 15
data_feed: iex

strategy:
  fast_ema: {fast_ema}
  slow_ema: {slow_ema}
""".strip(),
        encoding="utf-8",
    )


def test_load_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "strategy.yaml"
    write_config(config_path)

    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")

    settings = load_settings(
        config_path=config_path,
        env_path=tmp_path / "missing.env",
    )

    assert settings.symbol == "SPY"
    assert settings.timeframe_minutes == 15
    assert settings.data_feed == "iex"
    assert settings.strategy.fast_ema == 9
    assert settings.strategy.slow_ema == 21


def test_missing_api_key_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "strategy.yaml"
    write_config(config_path)

    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")

    with pytest.raises(
        ValueError,
        match="ALPACA_API_KEY is missing",
    ):
        load_settings(
            config_path=config_path,
            env_path=tmp_path / "missing.env",
        )


def test_fast_ema_must_be_smaller_than_slow_ema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "strategy.yaml"
    write_config(config_path, fast_ema=21, slow_ema=9)

    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")

    with pytest.raises(
        ValueError,
        match="fast_ema must be smaller than slow_ema",
    ):
        load_settings(
            config_path=config_path,
            env_path=tmp_path / "missing.env",
        )
