"""Tests for persistent strategy-owned position state."""

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from trading_bot.execution.position_state import (
    JsonPositionStateStore,
    PositionPhase,
    PositionStateError,
    TrackedPosition,
)


def test_position_state_round_trip(
    tmp_path: Path,
) -> None:
    path = tmp_path / "position.json"
    store = JsonPositionStateStore(path)

    store.save(
        TrackedPosition(
            symbol="spy",
            quantity=2.0,
            average_entry_price=500.25,
            updated_at=datetime(
                2026,
                1,
                2,
                15,
                0,
                tzinfo=timezone.utc,
            ),
            source_order_id="order-1",
            source_client_order_id="signal-1",
        )
    )

    restored = store.load("SPY")

    assert restored is not None
    assert restored.symbol == "SPY"
    assert restored.quantity == pytest.approx(2.0)
    assert restored.average_entry_price == pytest.approx(
        500.25
    )
    assert restored.source_order_id == "order-1"


def test_flat_state_removes_average_price(
    tmp_path: Path,
) -> None:
    store = JsonPositionStateStore(
        tmp_path / "position.json"
    )

    store.save(
        TrackedPosition.flat(
            symbol="SPY",
            updated_at=datetime.now(
                timezone.utc
            ),
        )
    )

    restored = store.load("SPY")

    assert restored is not None
    assert restored.quantity == pytest.approx(0.0)
    assert restored.average_entry_price is None


def test_missing_state_returns_none(
    tmp_path: Path,
) -> None:
    store = JsonPositionStateStore(
        tmp_path / "missing.json"
    )

    assert store.load("SPY") is None


def test_invalid_state_file_fails(
    tmp_path: Path,
) -> None:
    path = tmp_path / "position.json"
    path.write_text(
        "not json",
        encoding="utf-8",
    )

    with pytest.raises(
        PositionStateError,
        match="could not be read",
    ):
        JsonPositionStateStore(
            path
        ).load("SPY")


@pytest.mark.parametrize("quantity", [0.0, 2.0])
def test_version_one_state_loads_without_silent_upgrade(
    tmp_path: Path,
    quantity: float,
) -> None:
    path = tmp_path / "position.json"
    payload = {
        "version": 1,
        "positions": {
            "SPY": {
                "symbol": "SPY",
                "quantity": quantity,
                "average_entry_price": 500.0 if quantity else None,
                "updated_at": "2026-07-21T20:00:00+00:00",
                "source_order_id": None,
                "source_client_order_id": None,
                "adopted": False,
            }
        },
    }
    original = json.dumps(payload, sort_keys=True)
    path.write_text(original, encoding="utf-8")

    restored = JsonPositionStateStore(path).load("SPY")

    assert restored.schema_version == 1
    assert restored.phase is (
        PositionPhase.RECONCILIATION_REQUIRED
        if quantity
        else PositionPhase.FLAT
    )
    assert restored.legacy_open is bool(quantity)
    assert json.loads(path.read_text(encoding="utf-8")) == payload

    if quantity:
        with pytest.raises(
            PositionStateError,
            match="cannot be upgraded",
        ):
            JsonPositionStateStore(path).save(restored)
