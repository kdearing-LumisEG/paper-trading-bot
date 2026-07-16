"""Tests for simulated position sizing."""

import pytest

from trading_bot.backtest.position_sizing import (
    PositionSizingError,
    PositionSizingModel,
)


def test_default_model_requests_one_share() -> None:
    model = PositionSizingModel()

    quantity = model.quantity_for_entry(
        fill_price=100.0,
        available_cash=10_000.0,
    )

    assert quantity == 1


def test_configured_quantity_is_returned() -> None:
    model = PositionSizingModel(
        quantity=25
    )

    quantity = model.quantity_for_entry(
        fill_price=100.0,
        available_cash=10_000.0,
    )

    assert quantity == 25


def test_required_cash_includes_commission() -> None:
    model = PositionSizingModel(
        quantity=10
    )

    required = model.required_cash(
        fill_price=100.0,
        commission=1.50,
    )

    assert required == pytest.approx(
        1_001.50
    )


def test_insufficient_cash_skips_entry() -> None:
    model = PositionSizingModel(
        quantity=10
    )

    quantity = model.quantity_for_entry(
        fill_price=100.0,
        available_cash=999.0,
        commission=1.0,
    )

    assert quantity == 0


def test_exact_cash_requirement_is_allowed() -> None:
    model = PositionSizingModel(
        quantity=10
    )

    quantity = model.quantity_for_entry(
        fill_price=100.0,
        available_cash=1_001.0,
        commission=1.0,
    )

    assert quantity == 10


def test_cash_fraction_can_block_entry() -> None:
    model = PositionSizingModel(
        quantity=10,
        max_cash_fraction=0.50,
    )

    quantity = model.quantity_for_entry(
        fill_price=100.0,
        available_cash=1_500.0,
    )

    assert quantity == 0


def test_cash_fraction_allows_position_within_limit() -> None:
    model = PositionSizingModel(
        quantity=5,
        max_cash_fraction=0.50,
    )

    quantity = model.quantity_for_entry(
        fill_price=100.0,
        available_cash=1_000.0,
    )

    assert quantity == 5


@pytest.mark.parametrize(
    ("quantity", "cash_fraction"),
    [
        (0, 1.0),
        (-1, 1.0),
        (1, 0.0),
        (1, -0.10),
        (1, 1.01),
    ],
)
def test_invalid_model_settings_fail(
    quantity: int,
    cash_fraction: float,
) -> None:
    with pytest.raises(
        PositionSizingError
    ):
        PositionSizingModel(
            quantity=quantity,
            max_cash_fraction=cash_fraction,
        )


@pytest.mark.parametrize(
    ("fill_price", "commission"),
    [
        (0.0, 0.0),
        (-1.0, 0.0),
        (100.0, -0.01),
    ],
)
def test_invalid_order_values_fail(
    fill_price: float,
    commission: float,
) -> None:
    model = PositionSizingModel()

    with pytest.raises(
        PositionSizingError
    ):
        model.required_cash(
            fill_price=fill_price,
            commission=commission,
        )


def test_negative_available_cash_fails() -> None:
    model = PositionSizingModel()

    with pytest.raises(
        PositionSizingError,
        match="available_cash cannot be negative",
    ):
        model.quantity_for_entry(
            fill_price=100.0,
            available_cash=-1.0,
        )