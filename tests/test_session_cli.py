"""CLI coverage for autonomous session operation."""

import signal

import pytest

from trading_bot.main import _raise_keyboard_interrupt, build_parser


def test_run_session_is_dry_run_by_default() -> None:
    arguments = build_parser().parse_args(["run-session"])
    assert arguments.command == "run-session"
    assert not arguments.execute


def test_run_session_execute_is_explicit() -> None:
    arguments = build_parser().parse_args(["run-session", "--execute"])
    assert arguments.execute


def test_no_live_session_option_exists() -> None:
    help_text = build_parser().format_help()
    assert "--live" not in help_text


@pytest.mark.skipif(not hasattr(signal, "SIGBREAK"), reason="Windows-only signal")
def test_windows_console_break_uses_graceful_interrupt_path() -> None:
    with pytest.raises(KeyboardInterrupt):
        _raise_keyboard_interrupt(signal.SIGBREAK, None)
