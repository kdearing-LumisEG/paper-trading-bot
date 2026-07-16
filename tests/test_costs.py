"""Tests for simulated execution costs."""

import pytest

from trading_bot.backtest.costs import (
    ExecutionCostError,
    ExecutionCostModel,
)


def test_default_model_has_no_costs() -> None:
    model = ExecutionCostModel()

    assert model.adjusted_fill_price(
        100.0,
        "buy",
    ) == pytest.approx(100.0)

    assert model.adjusted_fill_price(
        100.0,
        "sell",
    ) == pytest.approx(100.0)

    assert model.commission_for_order(1) == 0.0


def test_buy_slippage_increases_fill_price() -> None:
    model = ExecutionCostModel(
        slippage_bps=10.0
    )

    result = model.adjusted_fill_price(
        reference_price=100.0,
        side="buy",
    )

    assert result == pytest.approx(100.10)


def test_sell_slippage_decreases_fill_price() -> None:
    model = ExecutionCostModel(
        slippage_bps=10.0
    )

    result = model.adjusted_fill_price(
        reference_price=100.0,
        side="sell",
    )

    assert result == pytest.approx(99.90)


def test_commission_is_charged_per_order() -> None:
    model = ExecutionCostModel(
        commission_per_order=1.25
    )

    assert model.commission_for_order(
        quantity=1
    ) == pytest.approx(1.25)

    assert model.commission_for_order(
        quantity=100
    ) == pytest.approx(1.25)


@pytest.mark.parametrize(
    ("commission", "slippage"),
    [
        (-0.01, 0.0),
        (0.0, -0.01),
    ],
)
def test_negative_assumptions_fail(
    commission: float,
    slippage: float,
) -> None:
    with pytest.raises(
        ExecutionCostError
    ):
        ExecutionCostModel(
            commission_per_order=commission,
            slippage_bps=slippage,
        )


def test_nonpositive_reference_price_fails() -> None:
    model = ExecutionCostModel()

    with pytest.raises(
        ExecutionCostError,
        match="reference_price must be positive",
    ):
        model.adjusted_fill_price(
            reference_price=0.0,
            side="buy",
        )


def test_nonpositive_quantity_fails() -> None:
    model = ExecutionCostModel()

    with pytest.raises(
        ExecutionCostError,
        match="quantity must be positive",
    ):
        model.commission_for_order(
            quantity=0
        )


def test_unknown_order_side_fails() -> None:
    model = ExecutionCostModel()

    with pytest.raises(
        ExecutionCostError,
        match="Unsupported order side",
    ):
        model.adjusted_fill_price(
            reference_price=100.0,
            side="invalid",  # type: ignore[arg-type]
        )