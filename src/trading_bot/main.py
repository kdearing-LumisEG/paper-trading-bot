"""Command-line entry point for manual Alpaca paper checks."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date, datetime
from enum import Enum
import json
from pathlib import Path

from trading_bot.broker.alpaca_client import (
    AlpacaPaperBroker,
)
from trading_bot.broker.models import (
    MarketOrderRequest,
    OrderSide,
)
from trading_bot.config import load_settings
from trading_bot.execution.kill_switch import (
    FileKillSwitch,
)
from trading_bot.execution.logging import (
    JsonlExecutionLogger,
)
from trading_bot.execution.models import (
    ExecutionSettings,
)
from trading_bot.execution.service import (
    PaperExecutionService,
)


def _json_default(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(
        f"Object of type {type(value).__name__} "
        "is not JSON serializable."
    )


def _print_json(value: object) -> None:
    if hasattr(value, "__dataclass_fields__"):
        value = asdict(value)

    print(
        json.dumps(
            value,
            indent=2,
            default=_json_default,
            sort_keys=True,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect or submit orders to an Alpaca paper account."
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

    for command in ("buy", "sell"):
        order_parser = subparsers.add_parser(
            command,
            help=(
                f"Create a {command} market-order attempt."
            ),
        )
        order_parser.add_argument(
            "--symbol",
            help=(
                "Stock symbol; defaults to strategy.yaml."
            ),
        )
        order_parser.add_argument(
            "--quantity",
            type=int,
            required=True,
        )
        order_parser.add_argument(
            "--client-order-id",
            required=True,
            help=(
                "Unique stable identifier used for duplicate protection."
            ),
        )
        order_parser.add_argument(
            "--execute",
            action="store_true",
            help=(
                "Submit to Alpaca paper trading. Without this "
                "flag the command is a dry run."
            ),
        )
        order_parser.add_argument(
            "--poll-interval-seconds",
            type=float,
            default=1.0,
        )
        order_parser.add_argument(
            "--max-poll-attempts",
            type=int,
            default=10,
        )

    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    settings = load_settings()

    broker = AlpacaPaperBroker(
        api_key=settings.alpaca_api_key,
        secret_key=settings.alpaca_secret_key,
    )

    service = PaperExecutionService(
        broker=broker,
        settings=ExecutionSettings(
            dry_run=not getattr(
                arguments,
                "execute",
                False,
            ),
            poll_interval_seconds=getattr(
                arguments,
                "poll_interval_seconds",
                1.0,
            ),
            max_poll_attempts=getattr(
                arguments,
                "max_poll_attempts",
                10,
            ),
        ),
        kill_switch=FileKillSwitch(
            arguments.kill_switch_path
        ),
        logger=JsonlExecutionLogger(
            Path("logs/execution/paper_orders.jsonl")
        ),
    )

    if arguments.command == "account":
        _print_json(service.get_account())
        return

    if arguments.command == "positions":
        _print_json(
            [
                asdict(position)
                for position in service.list_positions()
            ]
        )
        return

    symbol = (
        arguments.symbol
        if arguments.symbol is not None
        else settings.symbol
    )

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

    result = service.execute_market_order(
        request
    )
    _print_json(result)


if __name__ == "__main__":
    main()
