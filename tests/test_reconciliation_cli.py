"""Tests for reconciliation and runtime-lock CLI behavior."""

from datetime import datetime, timezone

from trading_bot.broker.models import (
    PositionSnapshot,
)
from trading_bot.execution.position_state import (
    JsonPositionStateStore,
    TrackedPosition,
)

from trading_bot.main import (
    _position_inspection_payload,
    build_parser,
)


class PositionService:
    """Return broker positions without exposing mutation methods."""

    def list_positions(
        self,
    ) -> list[PositionSnapshot]:
        return [
            PositionSnapshot(
                symbol="SPY",
                quantity=2.0,
                average_entry_price=500.0,
                market_value=1010.0,
                unrealized_pnl=10.0,
            )
        ]


def test_reconcile_defaults_to_read_only() -> None:
    arguments = build_parser().parse_args(
        [
            "reconcile",
        ]
    )

    assert arguments.command == "reconcile"
    assert arguments.adopt_position is False


def test_reconcile_adoption_is_explicit() -> None:
    arguments = build_parser().parse_args(
        [
            "reconcile",
            "--adopt-position",
        ]
    )

    assert arguments.adopt_position is True


def test_clear_lock_requires_separate_confirmation() -> None:
    arguments = build_parser().parse_args(
        [
            "clear-lock",
        ]
    )

    assert arguments.command == "clear-lock"
    assert arguments.confirm is False


def test_positions_distinguishes_broker_and_local_state(
    tmp_path,
) -> None:
    state_path = tmp_path / "position_state.json"
    store = JsonPositionStateStore(state_path)
    store.save(
        TrackedPosition(
            symbol="SPY",
            quantity=2.0,
            average_entry_price=500.0,
            updated_at=datetime(
                2026,
                7,
                21,
                tzinfo=timezone.utc,
            ),
            adopted=False,
        )
    )

    payload = _position_inspection_payload(
        service=PositionService(),
        position_store=store,
        symbol="SPY",
    )

    assert payload["broker_positions"] == [
        {
            "average_entry_price": 500.0,
            "market_value": 1010.0,
            "quantity": 2.0,
            "symbol": "SPY",
            "unrealized_pnl": 10.0,
        }
    ]
    assert payload["tracked_position"] == {
        "adopted": False,
        "average_entry_price": 500.0,
        "quantity": 2.0,
        "source_client_order_id": None,
        "source_order_id": None,
        "symbol": "SPY",
        "updated_at": datetime(
            2026,
            7,
            21,
            tzinfo=timezone.utc,
        ),
    }
