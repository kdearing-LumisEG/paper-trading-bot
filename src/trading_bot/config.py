"""Application configuration loading and validation."""

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import yaml


@dataclass(frozen=True)
class StrategySettings:
    """Parameters for the initial deterministic strategy."""

    fast_ema: int
    slow_ema: int


@dataclass(frozen=True)
class Settings:
    """Validated settings used throughout the application."""

    alpaca_api_key: str
    alpaca_secret_key: str
    symbol: str
    timeframe_minutes: int
    data_feed: str
    strategy: StrategySettings


def _read_yaml(path: Path) -> dict[str, Any]:
    """Read and validate a YAML configuration file."""

    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        contents = yaml.safe_load(file)

    if not isinstance(contents, dict):
        raise ValueError("Configuration file must contain a YAML mapping.")

    return contents


def load_settings(
    config_path: Path = Path("config/strategy.yaml"),
    env_path: Path = Path(".env"),
) -> Settings:
    """Load private credentials and non-secret project settings."""

    load_dotenv(dotenv_path=env_path, override=False)

    api_key = os.getenv("ALPACA_API_KEY", "").strip()
    secret_key = os.getenv("ALPACA_SECRET_KEY", "").strip()

    if not api_key:
        raise ValueError("ALPACA_API_KEY is missing.")
    if not secret_key:
        raise ValueError("ALPACA_SECRET_KEY is missing.")

    config = _read_yaml(config_path)

    try:
        symbol = str(config["symbol"]).strip().upper()
        timeframe_minutes = int(config["timeframe_minutes"])
        data_feed = str(config["data_feed"]).strip().lower()

        strategy_config = config["strategy"]
        fast_ema = int(strategy_config["fast_ema"])
        slow_ema = int(strategy_config["slow_ema"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "Configuration contains missing or invalid values."
        ) from exc

    if not symbol:
        raise ValueError("symbol cannot be empty.")
    if timeframe_minutes <= 0:
        raise ValueError("timeframe_minutes must be positive.")
    if data_feed not in {"iex", "sip"}:
        raise ValueError("data_feed must be either 'iex' or 'sip'.")
    if fast_ema <= 0 or slow_ema <= 0:
        raise ValueError("EMA periods must be positive.")
    if fast_ema >= slow_ema:
        raise ValueError("fast_ema must be smaller than slow_ema.")

    return Settings(
        alpaca_api_key=api_key,
        alpaca_secret_key=secret_key,
        symbol=symbol,
        timeframe_minutes=timeframe_minutes,
        data_feed=data_feed,
        strategy=StrategySettings(
            fast_ema=fast_ema,
            slow_ema=slow_ema,
        ),
    )
