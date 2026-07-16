"""Execution-cost assumptions for simulated trades."""

from dataclasses import dataclass
from typing import Literal


OrderSide = Literal["buy", "sell"]


class ExecutionCostError(ValueError):
    """Raised when execution-cost assumptions are invalid."""


@dataclass(frozen=True)
class ExecutionCostModel:
    """Commission and slippage assumptions for simulated orders."""

    commission_per_order: float = 0.0
    slippage_bps: float = 0.0

    def __post_init__(self) -> None:
        if self.commission_per_order < 0:
            raise ExecutionCostError(
                "commission_per_order cannot be negative."
            )

        if self.slippage_bps < 0:
            raise ExecutionCostError(
                "slippage_bps cannot be negative."
            )

    def adjusted_fill_price(
        self,
        reference_price: float,
        side: OrderSide,
    ) -> float:
        """Return a reference price adjusted against the trader."""

        if reference_price <= 0:
            raise ExecutionCostError(
                "reference_price must be positive."
            )

        slippage_fraction = (
            self.slippage_bps / 10_000
        )

        if side == "buy":
            return reference_price * (
                1 + slippage_fraction
            )

        if side == "sell":
            return reference_price * (
                1 - slippage_fraction
            )

        raise ExecutionCostError(
            f"Unsupported order side: {side}"
        )

    def commission_for_order(
        self,
        quantity: int,
    ) -> float:
        """Return the flat commission for a nonzero order."""

        if quantity <= 0:
            raise ExecutionCostError(
                "quantity must be positive."
            )

        return self.commission_per_order