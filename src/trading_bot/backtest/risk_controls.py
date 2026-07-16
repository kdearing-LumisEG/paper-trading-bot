"""Risk-control rules for simulated trading."""

from dataclasses import dataclass
import math


class RiskControlError(ValueError):
    """Raised when risk-control settings or inputs are invalid."""


def _validate_positive_integer(
    value: int,
    field_name: str,
) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
    ):
        raise RiskControlError(
            f"{field_name} must be a positive integer."
        )


@dataclass(frozen=True)
class DailyLossLimit:
    """Block new entries after a realized daily-loss threshold."""

    max_daily_loss: float

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.max_daily_loss)
            or self.max_daily_loss <= 0
        ):
            raise RiskControlError(
                "max_daily_loss must be a finite positive value."
            )

    def entry_allowed(
        self,
        realized_net_pnl: float,
    ) -> bool:
        """Return whether another entry is allowed today."""

        self._validate_realized_pnl(
            realized_net_pnl
        )

        return (
            realized_net_pnl
            > -self.max_daily_loss
        )

    def remaining_loss_capacity(
        self,
        realized_net_pnl: float,
    ) -> float:
        """Return loss capacity remaining before entries are blocked."""

        self._validate_realized_pnl(
            realized_net_pnl
        )

        return max(
            0.0,
            self.max_daily_loss
            + realized_net_pnl,
        )

    @staticmethod
    def _validate_realized_pnl(
        realized_net_pnl: float,
    ) -> None:
        if not math.isfinite(
            realized_net_pnl
        ):
            raise RiskControlError(
                "realized_net_pnl must be finite."
            )


@dataclass(frozen=True)
class MaxTradesPerSession:
    """Block new entries after a session trade-count limit."""

    max_trades: int

    def __post_init__(self) -> None:
        _validate_positive_integer(
            self.max_trades,
            "max_trades",
        )

    def entry_allowed(
        self,
        trades_started: int,
    ) -> bool:
        """Return whether another trade may start this session."""

        if trades_started < 0:
            raise RiskControlError(
                "trades_started cannot be negative."
            )

        return trades_started < self.max_trades


@dataclass(frozen=True)
class ConsecutiveLossLimit:
    """Block new entries after consecutive realized losses."""

    max_consecutive_losses: int

    def __post_init__(self) -> None:
        _validate_positive_integer(
            self.max_consecutive_losses,
            "max_consecutive_losses",
        )

    def entry_allowed(
        self,
        consecutive_losses: int,
    ) -> bool:
        """Return whether another entry is allowed this session."""

        if consecutive_losses < 0:
            raise RiskControlError(
                "consecutive_losses cannot be negative."
            )

        return (
            consecutive_losses
            < self.max_consecutive_losses
        )
