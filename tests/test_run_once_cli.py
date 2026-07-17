"""Tests for one-shot market-signal CLI parsing."""

from trading_bot.main import (
    build_parser,
)


def test_run_once_defaults_to_dry_run() -> None:
    arguments = build_parser().parse_args(
        [
            "run-once",
        ]
    )

    assert arguments.command == "run-once"
    assert arguments.execute is False
    assert arguments.force is False


def test_run_once_requires_explicit_execution() -> None:
    arguments = build_parser().parse_args(
        [
            "run-once",
            "--execute",
            "--force",
        ]
    )

    assert arguments.execute is True
    assert arguments.force is True
