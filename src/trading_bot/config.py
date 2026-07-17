"""Application configuration loading and validation."""

from dataclasses import dataclass, field
import math
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
    name: str = "ema_crossover_9_21"


@dataclass(frozen=True)
class PaperExecutionSettings:
    """Safe defaults for signal-driven paper execution."""

    quantity: int = 1
    poll_interval_seconds: float = 1.0
    max_poll_attempts: int = 10
    max_daily_loss: float | None = 25.0
    max_trades_per_session: int | None = 3
    max_consecutive_losses: int | None = 2
    order_log_path: Path = Path(
        "logs/execution/paper_orders.jsonl"
    )
    decision_log_path: Path = Path(
        "logs/execution/signal_decisions.jsonl"
    )
    risk_state_path: Path = Path(
        "logs/execution/session_risk_state.json"
    )


@dataclass(frozen=True)
class MarketSignalSettings:
    """Settings for one-shot market-data signal evaluation."""

    lookback_calendar_days: int = 14
    bar_staleness_grace_seconds: float = 120.0
    flatten_minutes_before_close: int = 15
    signal_state_path: Path = Path(
        "logs/execution/market_signal_state.json"
    )


@dataclass(frozen=True)
class Settings:
    """Validated settings used throughout the application."""

    alpaca_api_key: str
    alpaca_secret_key: str
    symbol: str
    timeframe_minutes: int
    data_feed: str
    strategy: StrategySettings
    paper_execution: PaperExecutionSettings = field(
        default_factory=PaperExecutionSettings
    )
    market_signal: MarketSignalSettings = field(
        default_factory=MarketSignalSettings
    )


def _read_yaml(path: Path) -> dict[str, Any]:
    """Read and validate a YAML configuration file."""

    if not path.exists():
        raise FileNotFoundError(
            f"Configuration file not found: {path}"
        )

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:
        contents = yaml.safe_load(file)

    if not isinstance(contents, dict):
        raise ValueError(
            "Configuration file must contain a YAML mapping."
        )

    return contents


def _optional_positive_float(
    value: object,
    field_name: str,
) -> float | None:
    if value is None:
        return None

    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{field_name} must be a positive number or null."
        ) from exc

    if not math.isfinite(result) or result <= 0:
        raise ValueError(
            f"{field_name} must be a positive number or null."
        )

    return result


def _optional_positive_int(
    value: object,
    field_name: str,
) -> int | None:
    if value is None:
        return None

    if isinstance(value, bool):
        raise ValueError(
            f"{field_name} must be a positive integer or null."
        )

    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{field_name} must be a positive integer or null."
        ) from exc

    if result <= 0 or result != value:
        raise ValueError(
            f"{field_name} must be a positive integer or null."
        )

    return result


def _positive_int(
    value: object,
    field_name: str,
) -> int:
    result = _optional_positive_int(
        value,
        field_name,
    )

    if result is None:
        raise ValueError(
            f"{field_name} must be a positive integer."
        )

    return result


def _positive_float(
    value: object,
    field_name: str,
) -> float:
    result = _optional_positive_float(
        value,
        field_name,
    )

    if result is None:
        raise ValueError(
            f"{field_name} must be a positive number."
        )

    return result


def _nonnegative_float(
    value: object,
    field_name: str,
) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{field_name} must be a finite nonnegative number."
        ) from exc

    if not math.isfinite(result) or result < 0:
        raise ValueError(
            f"{field_name} must be a finite nonnegative number."
        )

    return result


def _path_setting(
    value: object,
    field_name: str,
) -> Path:
    result = str(value).strip()

    if not result:
        raise ValueError(
            f"{field_name} cannot be empty."
        )

    return Path(result)


def load_settings(
    config_path: Path = Path("config/strategy.yaml"),
    env_path: Path = Path(".env"),
) -> Settings:
    """Load private credentials and non-secret project settings."""

    load_dotenv(
        dotenv_path=env_path,
        override=False,
    )

    api_key = os.getenv(
        "ALPACA_API_KEY",
        "",
    ).strip()

    secret_key = os.getenv(
        "ALPACA_SECRET_KEY",
        "",
    ).strip()

    if not api_key:
        raise ValueError(
            "ALPACA_API_KEY is missing."
        )

    if not secret_key:
        raise ValueError(
            "ALPACA_SECRET_KEY is missing."
        )

    config = _read_yaml(config_path)

    try:
        symbol = str(
            config["symbol"]
        ).strip().upper()

        timeframe_minutes = int(
            config["timeframe_minutes"]
        )

        data_feed = str(
            config["data_feed"]
        ).strip().lower()

        strategy_config = config["strategy"]

        if not isinstance(
            strategy_config,
            dict,
        ):
            raise TypeError(
                "strategy must be a mapping."
            )

        fast_ema = int(
            strategy_config["fast_ema"]
        )
        slow_ema = int(
            strategy_config["slow_ema"]
        )

        strategy_name = str(
            strategy_config.get(
                "name",
                f"ema_crossover_{fast_ema}_{slow_ema}",
            )
        ).strip()

        execution_config = config.get(
            "paper_execution",
            {},
        )

        if not isinstance(
            execution_config,
            dict,
        ):
            raise TypeError(
                "paper_execution must be a mapping."
            )

        quantity = _positive_int(
            execution_config.get(
                "quantity",
                1,
            ),
            "paper_execution.quantity",
        )

        poll_interval_seconds = (
            _positive_float(
                execution_config.get(
                    "poll_interval_seconds",
                    1.0,
                ),
                (
                    "paper_execution."
                    "poll_interval_seconds"
                ),
            )
        )

        max_poll_attempts = _positive_int(
            execution_config.get(
                "max_poll_attempts",
                10,
            ),
            (
                "paper_execution."
                "max_poll_attempts"
            ),
        )

        max_daily_loss = (
            _optional_positive_float(
                execution_config.get(
                    "max_daily_loss"
                ),
                (
                    "paper_execution."
                    "max_daily_loss"
                ),
            )
        )

        max_trades_per_session = (
            _optional_positive_int(
                execution_config.get(
                    "max_trades_per_session"
                ),
                (
                    "paper_execution."
                    "max_trades_per_session"
                ),
            )
        )

        max_consecutive_losses = (
            _optional_positive_int(
                execution_config.get(
                    "max_consecutive_losses"
                ),
                (
                    "paper_execution."
                    "max_consecutive_losses"
                ),
            )
        )

        order_log_path = _path_setting(
            execution_config.get(
                "order_log_path",
                (
                    "logs/execution/"
                    "paper_orders.jsonl"
                ),
            ),
            (
                "paper_execution."
                "order_log_path"
            ),
        )

        decision_log_path = _path_setting(
            execution_config.get(
                "decision_log_path",
                (
                    "logs/execution/"
                    "signal_decisions.jsonl"
                ),
            ),
            (
                "paper_execution."
                "decision_log_path"
            ),
        )

        risk_state_path = _path_setting(
            execution_config.get(
                "risk_state_path",
                (
                    "logs/execution/"
                    "session_risk_state.json"
                ),
            ),
            (
                "paper_execution."
                "risk_state_path"
            ),
        )

        market_config = config.get(
            "market_signal",
            {},
        )

        if not isinstance(
            market_config,
            dict,
        ):
            raise TypeError(
                "market_signal must be a mapping."
            )

        lookback_calendar_days = _positive_int(
            market_config.get(
                "lookback_calendar_days",
                14,
            ),
            (
                "market_signal."
                "lookback_calendar_days"
            ),
        )

        bar_staleness_grace_seconds = (
            _nonnegative_float(
                market_config.get(
                    "bar_staleness_grace_seconds",
                    120.0,
                ),
                (
                    "market_signal."
                    "bar_staleness_grace_seconds"
                ),
            )
        )

        flatten_minutes_before_close = (
            _positive_int(
                market_config.get(
                    "flatten_minutes_before_close",
                    15,
                ),
                (
                    "market_signal."
                    "flatten_minutes_before_close"
                ),
            )
        )

        signal_state_path = _path_setting(
            market_config.get(
                "signal_state_path",
                (
                    "logs/execution/"
                    "market_signal_state.json"
                ),
            ),
            (
                "market_signal."
                "signal_state_path"
            ),
        )

    except (
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "Configuration contains missing or invalid values."
        ) from exc

    if not symbol:
        raise ValueError(
            "symbol cannot be empty."
        )

    if timeframe_minutes <= 0:
        raise ValueError(
            "timeframe_minutes must be positive."
        )

    if data_feed not in {
        "iex",
        "sip",
    }:
        raise ValueError(
            "data_feed must be either 'iex' or 'sip'."
        )

    if (
        fast_ema <= 0
        or slow_ema <= 0
    ):
        raise ValueError(
            "EMA periods must be positive."
        )

    if fast_ema >= slow_ema:
        raise ValueError(
            "fast_ema must be smaller than slow_ema."
        )

    if not strategy_name:
        raise ValueError(
            "strategy.name cannot be empty."
        )

    return Settings(
        alpaca_api_key=api_key,
        alpaca_secret_key=secret_key,
        symbol=symbol,
        timeframe_minutes=(
            timeframe_minutes
        ),
        data_feed=data_feed,
        strategy=StrategySettings(
            name=strategy_name,
            fast_ema=fast_ema,
            slow_ema=slow_ema,
        ),
        paper_execution=(
            PaperExecutionSettings(
                quantity=quantity,
                poll_interval_seconds=(
                    poll_interval_seconds
                ),
                max_poll_attempts=(
                    max_poll_attempts
                ),
                max_daily_loss=(
                    max_daily_loss
                ),
                max_trades_per_session=(
                    max_trades_per_session
                ),
                max_consecutive_losses=(
                    max_consecutive_losses
                ),
                order_log_path=(
                    order_log_path
                ),
                decision_log_path=(
                    decision_log_path
                ),
                risk_state_path=(
                    risk_state_path
                ),
            )
        ),
        market_signal=MarketSignalSettings(
            lookback_calendar_days=(
                lookback_calendar_days
            ),
            bar_staleness_grace_seconds=(
                bar_staleness_grace_seconds
            ),
            flatten_minutes_before_close=(
                flatten_minutes_before_close
            ),
            signal_state_path=(
                signal_state_path
            ),
        ),
    )
