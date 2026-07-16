"""Risk-control rules for simulated trading."""

from dataclasses import dataclass
import math


class RiskControlError(ValueError):
    """Raised when risk-control settings or inputs are invalid."""


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