"""Command-line entry point for safe Alpaca paper trading."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date, datetime
from enum import Enum
import json
from pathlib import Path

from trading_bot.backtest.risk_controls import (
    ConsecutiveLossLimit,
    DailyLossLimit,
    MaxTradesPerSession,
)
from trading_bot.backtest.risk_manager import (
    SessionRiskConfig,
)
from trading_bot.broker.alpaca_client import (
    AlpacaPaperBroker,
)
from trading_bot.broker.models import (
    MarketOrderRequest,
    OrderSide,
)
from trading_bot.config import (
    Settings,
    load_settings,
)
from trading_bot.execution.coordinator import (
    SignalExecutionCoordinator,
)
from trading_bot.execution.decision_logging import (
    JsonlSignalDecisionLogger,
)
from trading_bot.execution.kill_switch import (
    FileKillSwitch,
)
from trading_bot.execution.logging import (
    JsonlExecutionLogger,
)
from trading_bot.execution.models import (
    ExecutionSettings,
)
from trading_bot.execution.risk_state import (
    JsonRiskStateStore,
)
from trading_bot.execution.service import (
    PaperExecutionService,
)
from trading_bot.execution.signal_models import (
    StrategySignal,
    StrategySignalEvent,
)
from trading_bot.runtime.cycle import (
    MarketSignalCycle,
    MarketSignalCycleSettings,
)
from trading_bot.runtime.market_data import (
    AlpacaRecentBarSource,
)
from trading_bot.runtime.signal_state import (
    JsonSignalStateStore,
)


def _json_default(
    value: object,
) -> object:
    if isinstance(value, Enum):
        return value.value

    if isinstance(
        value,
        (
            date,
            datetime,
        ),
    ):
        return value.isoformat()

    if isinstance(value, Path):
        return str(value)

    raise TypeError(
        f"Object of type "
        f"{type(value).__name__} "
        "is not JSON serializable."
    )


def _print_json(
    value: object,
) -> None:
    if hasattr(
        value,
        "__dataclass_fields__",
    ):
        value = asdict(value)

    print(
        json.dumps(
            value,
            indent=2,
            default=_json_default,
            sort_keys=True,
        )
    )


def _parse_datetime(
    value: str,
) -> datetime:
    normalized = value.strip()

    if normalized.endswith("Z"):
        normalized = (
            normalized[:-1]
            + "+00:00"
        )

    try:
        result = datetime.fromisoformat(
            normalized
        )
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "signal time must be ISO-8601, "
            "for example 2026-01-02T15:00:00Z"
        ) from exc

    return result


def _add_execution_arguments(
    parser: argparse.ArgumentParser,
    *,
    include_client_order_id: bool,
) -> None:
    if include_client_order_id:
        parser.add_argument(
            "--client-order-id",
            required=True,
            help=(
                "Unique stable identifier used "
                "for duplicate protection."
            ),
        )

    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Submit to Alpaca paper trading. "
            "Without this flag the command "
            "is a dry run."
        ),
    )

    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        help=(
            "Override the configured polling interval."
        ),
    )

    parser.add_argument(
        "--max-poll-attempts",
        type=int,
        help=(
            "Override the configured polling limit."
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the paper-trading command-line parser."""

    parser = argparse.ArgumentParser(
        description=(
            "Inspect or safely submit orders "
            "to an Alpaca paper account."
        )
    )

    parser.add_argument(
        "--kill-switch-path",
        type=Path,
        default=Path("STOP_TRADING"),
        help=(
            "Existing marker file that blocks new orders."
        ),
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    subparsers.add_parser(
        "account",
        help="Show the paper-account snapshot.",
    )

    subparsers.add_parser(
        "positions",
        help="Show open paper positions.",
    )

    subparsers.add_parser(
        "risk-state",
        help=(
            "Show persisted paper-trading "
            "session risk state."
        ),
    )

    for command in (
        "buy",
        "sell",
    ):
        order_parser = subparsers.add_parser(
            command,
            help=(
                f"Create a {command} "
                "market-order attempt."
            ),
        )

        order_parser.add_argument(
            "--symbol",
            help=(
                "Stock symbol; defaults "
                "to strategy.yaml."
            ),
        )

        order_parser.add_argument(
            "--quantity",
            type=int,
            required=True,
        )

        _add_execution_arguments(
            order_parser,
            include_client_order_id=True,
        )

    signal_parser = subparsers.add_parser(
        "signal",
        help=(
            "Pass one deterministic strategy signal "
            "through position, risk, and execution checks."
        ),
    )

    signal_parser.add_argument(
        "--signal",
        choices=[
            signal.value
            for signal in StrategySignal
        ],
        required=True,
    )

    signal_parser.add_argument(
        "--signal-time",
        type=_parse_datetime,
        required=True,
    )

    signal_parser.add_argument(
        "--symbol",
        help=(
            "Stock symbol; defaults "
            "to strategy.yaml."
        ),
    )

    signal_parser.add_argument(
        "--quantity",
        type=int,
        help=(
            "Entry quantity; exits close "
            "the current whole-share position."
        ),
    )

    signal_parser.add_argument(
        "--strategy-name",
        help=(
            "Strategy identifier; defaults "
            "to strategy.yaml."
        ),
    )

    _add_execution_arguments(
        signal_parser,
        include_client_order_id=False,
    )

    run_once_parser = subparsers.add_parser(
        "run-once",
        help=(
            "Fetch recent bars, generate the latest "
            "closed-bar signal, and handle it once."
        ),
    )

    run_once_parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Reprocess the latest completed bar even "
            "when it is already recorded."
        ),
    )

    _add_execution_arguments(
        run_once_parser,
        include_client_order_id=False,
    )

    return parser


def _risk_config(
    settings: Settings,
) -> SessionRiskConfig:
    execution = settings.paper_execution

    return SessionRiskConfig(
        daily_loss_limit=(
            DailyLossLimit(
                execution.max_daily_loss
            )
            if execution.max_daily_loss
            is not None
            else None
        ),
        max_trades_per_session=(
            MaxTradesPerSession(
                execution
                .max_trades_per_session
            )
            if execution
            .max_trades_per_session
            is not None
            else None
        ),
        consecutive_loss_limit=(
            ConsecutiveLossLimit(
                execution
                .max_consecutive_losses
            )
            if execution
            .max_consecutive_losses
            is not None
            else None
        ),
    )


def _execution_service(
    settings: Settings,
    arguments: argparse.Namespace,
) -> PaperExecutionService:
    execution = settings.paper_execution

    poll_interval_seconds = (
        arguments.poll_interval_seconds
        if getattr(
            arguments,
            "poll_interval_seconds",
            None,
        )
        is not None
        else execution.poll_interval_seconds
    )

    max_poll_attempts = (
        arguments.max_poll_attempts
        if getattr(
            arguments,
            "max_poll_attempts",
            None,
        )
        is not None
        else execution.max_poll_attempts
    )

    broker = AlpacaPaperBroker(
        api_key=settings.alpaca_api_key,
        secret_key=settings.alpaca_secret_key,
    )

    return PaperExecutionService(
        broker=broker,
        settings=ExecutionSettings(
            dry_run=not getattr(
                arguments,
                "execute",
                False,
            ),
            poll_interval_seconds=(
                poll_interval_seconds
            ),
            max_poll_attempts=(
                max_poll_attempts
            ),
        ),
        kill_switch=FileKillSwitch(
            arguments.kill_switch_path
        ),
        logger=JsonlExecutionLogger(
            execution.order_log_path
        ),
    )


def _signal_coordinator(
    *,
    settings: Settings,
    service: PaperExecutionService,
    risk_manager,
    risk_store: JsonRiskStateStore,
) -> SignalExecutionCoordinator:
    execution = settings.paper_execution

    return SignalExecutionCoordinator(
        execution_service=service,
        risk_manager=risk_manager,
        risk_state_store=risk_store,
        logger=JsonlSignalDecisionLogger(
            execution.decision_log_path
        ),
    )


def main() -> None:
    """Run one manual paper-trading command."""

    arguments = (
        build_parser().parse_args()
    )

    settings = load_settings()
    execution = settings.paper_execution

    risk_store = JsonRiskStateStore(
        execution.risk_state_path
    )

    risk_manager = risk_store.load(
        _risk_config(settings)
    )

    if arguments.command == "risk-state":
        _print_json(
            risk_manager.export_state()
        )
        return

    service = _execution_service(
        settings=settings,
        arguments=arguments,
    )

    if arguments.command == "account":
        _print_json(
            service.get_account()
        )
        return

    if arguments.command == "positions":
        _print_json(
            [
                asdict(position)
                for position
                in service.list_positions()
            ]
        )
        return

    if arguments.command == "run-once":
        coordinator = _signal_coordinator(
            settings=settings,
            service=service,
            risk_manager=risk_manager,
            risk_store=risk_store,
        )

        market_settings = (
            settings.market_signal
        )

        cycle = MarketSignalCycle(
            bar_source=AlpacaRecentBarSource(
                api_key=settings.alpaca_api_key,
                secret_key=(
                    settings.alpaca_secret_key
                ),
            ),
            clock_source=service,
            signal_handler=coordinator,
            settings=MarketSignalCycleSettings(
                strategy_name=(
                    settings.strategy.name
                ),
                symbol=settings.symbol,
                timeframe_minutes=(
                    settings.timeframe_minutes
                ),
                fast_ema=(
                    settings.strategy.fast_ema
                ),
                slow_ema=(
                    settings.strategy.slow_ema
                ),
                entry_quantity=(
                    execution.quantity
                ),
                data_feed=settings.data_feed,
                lookback_calendar_days=(
                    market_settings
                    .lookback_calendar_days
                ),
                bar_staleness_grace_seconds=(
                    market_settings
                    .bar_staleness_grace_seconds
                ),
                flatten_minutes_before_close=(
                    market_settings
                    .flatten_minutes_before_close
                ),
            ),
            signal_state_store=JsonSignalStateStore(
                market_settings.signal_state_path
            ),
        )

        _print_json(
            cycle.run(
                force=arguments.force
            )
        )
        return

    symbol = (
        arguments.symbol
        if arguments.symbol is not None
        else settings.symbol
    )

    if arguments.command == "signal":
        coordinator = _signal_coordinator(
            settings=settings,
            service=service,
            risk_manager=risk_manager,
            risk_store=risk_store,
        )

        event = StrategySignalEvent(
            strategy_name=(
                arguments.strategy_name
                if arguments.strategy_name
                is not None
                else settings.strategy.name
            ),
            symbol=symbol,
            signal=StrategySignal(
                arguments.signal
            ),
            signal_time=(
                arguments.signal_time
            ),
            entry_quantity=(
                arguments.quantity
                if arguments.quantity
                is not None
                else execution.quantity
            ),
        )

        _print_json(
            coordinator.handle(event)
        )
        return

    side = (
        OrderSide.BUY
        if arguments.command == "buy"
        else OrderSide.SELL
    )

    request = MarketOrderRequest(
        symbol=symbol,
        quantity=arguments.quantity,
        side=side,
        client_order_id=(
            arguments.client_order_id
        ),
    )

    _print_json(
        service.execute_market_order(
            request
        )
    )


if __name__ == "__main__":
    main()
