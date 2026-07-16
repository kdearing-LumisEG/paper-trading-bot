"""Position-sizing rules for simulated entries."""

from dataclasses import dataclass


class PositionSizingError(ValueError):
    """Raised when position-sizing inputs are invalid."""


@dataclass(frozen=True)
class PositionSizingModel:
    """Fixed-quantity sizing with a cash-allocation limit."""

    quantity: int = 1
    max_cash_fraction: float = 1.0

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise PositionSizingError(
                "quantity must be positive."
            )

        if not 0 < self.max_cash_fraction <= 1:
            raise PositionSizingError(
                "max_cash_fraction must be greater than "
                "zero and no greater than one."
            )

    def required_cash(
        self,
        fill_price: float,
        commission: float = 0.0,
    ) -> float:
        """Return the cash required for the configured position."""

        if fill_price <= 0:
            raise PositionSizingError(
                "fill_price must be positive."
            )

        if commission < 0:
            raise PositionSizingError(
                "commission cannot be negative."
            )

        return (
            fill_price * self.quantity
            + commission
        )

    def quantity_for_entry(
        self,
        fill_price: float,
        available_cash: float,
        commission: float = 0.0,
    ) -> int:
        """Return the configured quantity or zero when unaffordable."""

        if available_cash < 0:
            raise PositionSizingError(
                "available_cash cannot be negative."
            )

        required_cash = self.required_cash(
            fill_price=fill_price,
            commission=commission,
        )

        allocation_limit = (
            available_cash
            * self.max_cash_fraction
        )

        if required_cash > allocation_limit:
            return 0

        return self.quantity
        