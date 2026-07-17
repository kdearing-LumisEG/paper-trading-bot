"""Tests for reconciliation and runtime-lock CLI parsing."""

from trading_bot.main import build_parser


def test_reconcile_defaults_to_read_only() -> None:
    arguments = build_parser().parse_args(
        [
            "reconcile",
        ]
    )

    assert arguments.command == "reconcile"
    assert arguments.adopt_position is False


def test_reconcile_adoption_is_explicit() -> None:
    arguments = build_parser().parse_args(
        [
            "reconcile",
            "--adopt-position",
        ]
    )

    assert arguments.adopt_position is True


def test_clear_lock_requires_separate_confirmation() -> None:
    arguments = build_parser().parse_args(
        [
            "clear-lock",
        ]
    )

    assert arguments.command == "clear-lock"
    assert arguments.confirm is False
