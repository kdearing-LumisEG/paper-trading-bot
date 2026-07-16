"""Centralized session-level risk state and entry decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Mapping

import pandas as pd

from trading_bot.backtest.models import Trade
from trading_bot.backtest.risk_controls import (
    ConsecutiveLossLimit,
    DailyLossLimit,
    MaxTradesPerSession,
)


DAILY_LOSS_REASON = "daily_loss_limit"
MAX_TRADES_REASON = "max_trades_per_session"
CONSECUTIVE_LOSSES_REASON = "consecutive_loss_limit"


@dataclass(frozen=True)
class SessionRiskConfig:
    """Optional controls applied independently to each trading session."""

    daily_loss_limit: DailyLossLimit | None = None
    max_trades_per_session: MaxTradesPerSession | None = None
    consecutive_loss_limit: ConsecutiveLossLimit | None = None

    def to_dict(self) -> dict[str, object]:
        """Return JSON-serializable risk settings."""

        return {
            "daily_loss_limit": (
                self.daily_loss_limit.max_daily_loss
                if self.daily_loss_limit is not None
                else None
            ),
            "max_trades_per_session": (
                self.max_trades_per_session.max_trades
                if self.max_trades_per_session is not None
                else None
            ),
            "max_consecutive_losses_per_session": (
                self.consecutive_loss_limit.max_consecutive_losses
                if self.consecutive_loss_limit is not None
                else None
            ),
        }


@dataclass(frozen=True)
class SessionRiskSnapshot:
    """Read-only view of risk state for one exchange session."""

    session_date: date
    realized_net_pnl: float
    trades_started: int
    consecutive_losses: int


@dataclass(frozen=True)
class RiskDecision:
    """Entry permission and the state used to make the decision."""

    allowed: bool
    reason: str | None
    snapshot: SessionRiskSnapshot


@dataclass
class _SessionRiskState:
    realized_net_pnl: float = 0.0
    trades_started: int = 0
    consecutive_losses: int = 0


class RiskManager:
    """Track session risk state and evaluate new entries."""

    def __init__(
        self,
        config: SessionRiskConfig | None = None,
    ) -> None:
        self._config = (
            config
            if config is not None
            else SessionRiskConfig()
        )
        self._states: dict[date, _SessionRiskState] = {}

    @staticmethod
    def _session_date(
        session: date | datetime | pd.Timestamp,
    ) -> date:
        if isinstance(session, date) and not isinstance(
            session,
            datetime,
        ):
            return session

        timestamp = pd.Timestamp(session)

        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")

        return timestamp.tz_convert(
            "America/New_York"
        ).date()

    def _state_for(
        self,
        session: date | datetime | pd.Timestamp,
    ) -> tuple[date, _SessionRiskState]:
        session_date = self._session_date(session)
        state = self._states.setdefault(
            session_date,
            _SessionRiskState(),
        )
        return session_date, state

    def snapshot(
        self,
        session: date | datetime | pd.Timestamp,
    ) -> SessionRiskSnapshot:
        """Return current state for one session."""

        session_date, state = self._state_for(session)

        return SessionRiskSnapshot(
            session_date=session_date,
            realized_net_pnl=state.realized_net_pnl,
            trades_started=state.trades_started,
            consecutive_losses=state.consecutive_losses,
        )

    def evaluate_entry(
        self,
        session: date | datetime | pd.Timestamp,
    ) -> RiskDecision:
        """Evaluate all configured controls in deterministic order."""

        snapshot = self.snapshot(session)

        daily_loss = self._config.daily_loss_limit
        if (
            daily_loss is not None
            and not daily_loss.entry_allowed(
                snapshot.realized_net_pnl
            )
        ):
            return RiskDecision(
                allowed=False,
                reason=DAILY_LOSS_REASON,
                snapshot=snapshot,
            )

        max_trades = self._config.max_trades_per_session
        if (
            max_trades is not None
            and not max_trades.entry_allowed(
                snapshot.trades_started
            )
        ):
            return RiskDecision(
                allowed=False,
                reason=MAX_TRADES_REASON,
                snapshot=snapshot,
            )

        consecutive_losses = (
            self._config.consecutive_loss_limit
        )
        if (
            consecutive_losses is not None
            and not consecutive_losses.entry_allowed(
                snapshot.consecutive_losses
            )
        ):
            return RiskDecision(
                allowed=False,
                reason=CONSECUTIVE_LOSSES_REASON,
                snapshot=snapshot,
            )

        return RiskDecision(
            allowed=True,
            reason=None,
            snapshot=snapshot,
        )

    def record_entry(
        self,
        session: date | datetime | pd.Timestamp,
    ) -> None:
        """Record that a new position was opened in a session."""

        _, state = self._state_for(session)
        state.trades_started += 1

    def record_trade(self, trade: Trade) -> None:
        """Record realized net P&L and update the loss streak."""

        _, state = self._state_for(trade.exit_time)
        net_pnl = trade.resolved_net_pnl

        state.realized_net_pnl += net_pnl

        if net_pnl < 0:
            state.consecutive_losses += 1
        else:
            state.consecutive_losses = 0

    def settings(self) -> dict[str, object]:
        """Return configured controls for reports."""

        return self._config.to_dict()

    def snapshots(self) -> Mapping[date, SessionRiskSnapshot]:
        """Return snapshots for all sessions observed so far."""

        return {
            session_date: SessionRiskSnapshot(
                session_date=session_date,
                realized_net_pnl=state.realized_net_pnl,
                trades_started=state.trades_started,
                consecutive_losses=state.consecutive_losses,
            )
            for session_date, state in self._states.items()
        }
