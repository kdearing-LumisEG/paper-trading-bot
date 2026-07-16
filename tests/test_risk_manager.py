"""Tests for centralized session risk management."""

from datetime import datetime, timezone

import pandas as pd

from trading_bot.backtest.models import Trade
from trading_bot.backtest.risk_controls import (
    ConsecutiveLossLimit,
    DailyLossLimit,
    MaxTradesPerSession,
)
from trading_bot.backtest.risk_manager import (
    CONSECUTIVE_LOSSES_REASON,
    DAILY_LOSS_REASON,
    MAX_TRADES_REASON,
    RiskManager,
    SessionRiskConfig,
)


def make_trade(
    *,
    exit_time: str,
    net_pnl: float,
) -> Trade:
    timestamp = pd.Timestamp(exit_time)

    return Trade(
        symbol="SPY",
        entry_signal_time=timestamp,
        entry_time=timestamp,
        entry_price=100.0,
        exit_signal_time=None,
        exit_time=timestamp,
        exit_price=100.0 + net_pnl,
        quantity=1,
        exit_reason="signal",
        gross_pnl=net_pnl,
        return_pct=net_pnl / 100.0,
        bars_held=1,
        net_pnl=net_pnl,
    )


def test_default_manager_allows_entries() -> None:
    manager = RiskManager()

    decision = manager.evaluate_entry(
        pd.Timestamp("2026-01-02T15:00:00Z")
    )

    assert decision.allowed
    assert decision.reason is None


def test_daily_loss_limit_blocks_entry() -> None:
    manager = RiskManager(
        SessionRiskConfig(
            daily_loss_limit=DailyLossLimit(10.0)
        )
    )

    manager.record_trade(
        make_trade(
            exit_time="2026-01-02T15:00:00Z",
            net_pnl=-10.0,
        )
    )

    decision = manager.evaluate_entry(
        pd.Timestamp("2026-01-02T16:00:00Z")
    )

    assert not decision.allowed
    assert decision.reason == DAILY_LOSS_REASON
    assert decision.snapshot.realized_net_pnl == -10.0


def test_max_trades_blocks_after_configured_count() -> None:
    manager = RiskManager(
        SessionRiskConfig(
            max_trades_per_session=MaxTradesPerSession(2)
        )
    )
    session = pd.Timestamp("2026-01-02T15:00:00Z")

    manager.record_entry(session)
    manager.record_entry(session)

    decision = manager.evaluate_entry(session)

    assert not decision.allowed
    assert decision.reason == MAX_TRADES_REASON
    assert decision.snapshot.trades_started == 2


def test_consecutive_losses_block_entry() -> None:
    manager = RiskManager(
        SessionRiskConfig(
            consecutive_loss_limit=ConsecutiveLossLimit(2)
        )
    )

    manager.record_trade(
        make_trade(
            exit_time="2026-01-02T15:00:00Z",
            net_pnl=-1.0,
        )
    )
    manager.record_trade(
        make_trade(
            exit_time="2026-01-02T16:00:00Z",
            net_pnl=-2.0,
        )
    )

    decision = manager.evaluate_entry(
        pd.Timestamp("2026-01-02T17:00:00Z")
    )

    assert not decision.allowed
    assert decision.reason == CONSECUTIVE_LOSSES_REASON
    assert decision.snapshot.consecutive_losses == 2


def test_win_resets_consecutive_loss_streak() -> None:
    manager = RiskManager(
        SessionRiskConfig(
            consecutive_loss_limit=ConsecutiveLossLimit(2)
        )
    )

    manager.record_trade(
        make_trade(
            exit_time="2026-01-02T15:00:00Z",
            net_pnl=-1.0,
        )
    )
    manager.record_trade(
        make_trade(
            exit_time="2026-01-02T16:00:00Z",
            net_pnl=1.0,
        )
    )

    decision = manager.evaluate_entry(
        pd.Timestamp("2026-01-02T17:00:00Z")
    )

    assert decision.allowed
    assert decision.snapshot.consecutive_losses == 0


def test_session_state_resets_on_next_exchange_day() -> None:
    manager = RiskManager(
        SessionRiskConfig(
            daily_loss_limit=DailyLossLimit(5.0),
            max_trades_per_session=MaxTradesPerSession(1),
            consecutive_loss_limit=ConsecutiveLossLimit(1),
        )
    )

    first_session = pd.Timestamp("2026-01-02T15:00:00Z")
    next_session = pd.Timestamp("2026-01-05T15:00:00Z")

    manager.record_entry(first_session)
    manager.record_trade(
        make_trade(
            exit_time="2026-01-02T16:00:00Z",
            net_pnl=-5.0,
        )
    )

    first_decision = manager.evaluate_entry(first_session)
    next_decision = manager.evaluate_entry(next_session)

    assert not first_decision.allowed
    assert next_decision.allowed
    assert next_decision.snapshot.realized_net_pnl == 0.0
    assert next_decision.snapshot.trades_started == 0
    assert next_decision.snapshot.consecutive_losses == 0


def test_settings_are_serializable_values() -> None:
    manager = RiskManager(
        SessionRiskConfig(
            daily_loss_limit=DailyLossLimit(25.0),
            max_trades_per_session=MaxTradesPerSession(3),
            consecutive_loss_limit=ConsecutiveLossLimit(2),
        )
    )

    assert manager.settings() == {
        "daily_loss_limit": 25.0,
        "max_trades_per_session": 3,
        "max_consecutive_losses_per_session": 2,
    }


def test_naive_datetime_is_treated_as_utc() -> None:
    manager = RiskManager()

    snapshot = manager.snapshot(
        datetime(2026, 1, 2, 15, 0, tzinfo=timezone.utc)
    )

    assert snapshot.session_date.isoformat() == "2026-01-02"
