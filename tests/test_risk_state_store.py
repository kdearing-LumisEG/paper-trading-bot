"""Tests for persistent paper-trading risk state."""

from pathlib import Path

import pytest

from trading_bot.backtest.risk_controls import (
    DailyLossLimit,
    MaxTradesPerSession,
)
from trading_bot.backtest.risk_manager import (
    SessionRiskConfig,
)
from trading_bot.execution.risk_state import (
    JsonRiskStateStore,
)


def test_risk_state_round_trip(
    tmp_path: Path,
) -> None:
    path = tmp_path / "risk.json"

    config = SessionRiskConfig(
        daily_loss_limit=DailyLossLimit(
            25.0
        ),
        max_trades_per_session=(
            MaxTradesPerSession(3)
        ),
    )

    store = JsonRiskStateStore(path)
    manager = store.load(config)

    manager.record_entry(
        session="2026-01-02T15:00:00Z"
    )

    manager.record_realized_pnl(
        session="2026-01-02T16:00:00Z",
        net_pnl=-5.0,
    )

    store.save(manager)

    restored = store.load(config)

    snapshot = restored.snapshot(
        "2026-01-02T17:00:00Z"
    )

    assert snapshot.trades_started == 1
    assert snapshot.realized_net_pnl == pytest.approx(
        -5.0
    )
    assert snapshot.consecutive_losses == 1


def test_missing_state_file_returns_empty_manager(
    tmp_path: Path,
) -> None:
    store = JsonRiskStateStore(
        tmp_path / "missing.json"
    )

    manager = store.load(
        SessionRiskConfig()
    )

    snapshot = manager.snapshot(
        "2026-01-02T15:00:00Z"
    )

    assert snapshot.trades_started == 0


def test_invalid_state_file_fails(
    tmp_path: Path,
) -> None:
    path = tmp_path / "risk.json"
    path.write_text(
        "not json",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="could not be read",
    ):
        JsonRiskStateStore(path).load(
            SessionRiskConfig()
        )
