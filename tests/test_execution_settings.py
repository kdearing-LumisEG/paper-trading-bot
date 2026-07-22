"""Tests for execution setting validation."""

import math

import pytest

from trading_bot.execution.models import (
    ExecutionSettings,
    ExecutionSettingsError,
)


@pytest.mark.parametrize(
    "value",
    [-1.0, math.inf, math.nan],
)
def test_invalid_poll_interval_fails(
    value: float,
) -> None:
    with pytest.raises(
        ExecutionSettingsError,
        match="finite and nonnegative",
    ):
        ExecutionSettings(
            poll_interval_seconds=value
        )


@pytest.mark.parametrize(
    "value",
    [0, -1, True, 1.5],
)
def test_invalid_poll_attempt_count_fails(
    value: object,
) -> None:
    with pytest.raises(
        ExecutionSettingsError,
        match="positive integer",
    ):
        ExecutionSettings(
            max_poll_attempts=value,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("value", [0.0, -1.0, math.inf, math.nan])
def test_invalid_cancellation_confirmation_duration_fails(
    value: float,
) -> None:
    with pytest.raises(
        ExecutionSettingsError,
        match="finite and positive",
    ):
        ExecutionSettings(
            cancellation_confirmation_poll_seconds=value,
        )


def test_cancellation_timeout_cannot_be_shorter_than_poll() -> None:
    with pytest.raises(
        ExecutionSettingsError,
        match="at least the poll interval",
    ):
        ExecutionSettings(
            cancellation_confirmation_poll_seconds=2,
            cancellation_confirmation_timeout_seconds=1,
        )
