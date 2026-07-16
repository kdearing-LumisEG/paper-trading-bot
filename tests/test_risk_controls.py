"""Tests for simulated trading risk controls."""

import math

import pytest

from trading_bot.backtest.risk_controls import (
    DailyLossLimit,
    RiskControlError,
)


def test_entry_allowed_before_any_loss() -> None:
    control = DailyLossLimit(
        max_daily_loss=100.0
    )

    assert control.entry_allowed(
        realized_net_pnl=0.0
    )


def test_entry_allowed_before_threshold() -> None:
    control = DailyLossLimit(
        max_daily_loss=100.0
    )

    assert control.entry_allowed(
        realized_net_pnl=-99.99
    )


def test_entry_blocked_at_threshold() -> None:
    control = DailyLossLimit(
        max_daily_loss=100.0
    )

    assert not control.entry_allowed(
        realized_net_pnl=-100.0
    )


def test_entry_blocked_beyond_threshold() -> None:
    control = DailyLossLimit(
        max_daily_loss=100.0
    )

    assert not control.entry_allowed(
        realized_net_pnl=-125.0
    )


def test_profit_increases_remaining_capacity() -> None:
    control = DailyLossLimit(
        max_daily_loss=100.0
    )

    assert control.remaining_loss_capacity(
        realized_net_pnl=25.0
    ) == pytest.approx(125.0)


def test_remaining_capacity_never_goes_negative() -> None:
    control = DailyLossLimit(
        max_daily_loss=100.0
    )

    assert control.remaining_loss_capacity(
        realized_net_pnl=-150.0
    ) == pytest.approx(0.0)


@pytest.mark.parametrize(
    "maximum_loss",
    [
        0.0,
        -1.0,
        math.inf,
        -math.inf,
        math.nan,
    ],
)
def test_invalid_daily_limits_fail(
    maximum_loss: float,
) -> None:
    with pytest.raises(
        RiskControlError,
        match="finite positive",
    ):
        DailyLossLimit(
            max_daily_loss=maximum_loss
        )


@pytest.mark.parametrize(
    "realized_pnl",
    [
        math.inf,
        -math.inf,
        math.nan,
    ],
)
def test_nonfinite_realized_pnl_fails(
    realized_pnl: float,
) -> None:
    control = DailyLossLimit(
        max_daily_loss=100.0
    )

    with pytest.raises(
        RiskControlError,
        match="realized_net_pnl must be finite",
    ):
        control.entry_allowed(
            realized_net_pnl=realized_pnl
        )
        