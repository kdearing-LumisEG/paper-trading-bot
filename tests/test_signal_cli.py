"""Tests for signal-execution command-line parsing."""

from trading_bot.execution.signal_models import (
    StrategySignal,
)
from trading_bot.main import (
    build_parser,
)


def test_signal_command_parses_safe_dry_run() -> None:
    arguments = build_parser().parse_args(
        [
            "signal",
            "--signal",
            "enter_long",
            "--signal-time",
            "2026-01-02T15:00:00Z",
        ]
    )

    assert arguments.command == "signal"
    assert arguments.signal == (
        StrategySignal.ENTER_LONG.value
    )
    assert arguments.execute is False


def test_signal_command_requires_explicit_execute_flag() -> None:
    arguments = build_parser().parse_args(
        [
            "signal",
            "--signal",
            "exit_long",
            "--signal-time",
            "2026-01-02T15:00:00Z",
            "--execute",
        ]
    )

    assert arguments.execute is True
