"""Tests for durable strategy order-intent state."""

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from trading_bot.broker.models import OrderSide
from trading_bot.execution.order_state import (
    JsonOrderStateStore,
    OrderIntent,
    OrderLifecycleState,
    OrderStateError,
)


NOW = datetime(2026, 7, 21, 20, 0, tzinfo=timezone.utc)


def intent(
    intent_id: str = "intent-1",
    client_order_id: str = "client-1",
    state: OrderLifecycleState = OrderLifecycleState.CREATED,
) -> OrderIntent:
    filled_quantity = 2.0 if state is OrderLifecycleState.FILLED else 0.0
    return OrderIntent(
        intent_id=intent_id,
        strategy_name="ema_9_21",
        symbol="SPY",
        timeframe_minutes=15,
        signal_bar_end=NOW,
        action="enter_long",
        side=OrderSide.BUY,
        requested_quantity=2,
        client_order_id=client_order_id,
        position_generation_id="pg-1",
        lifecycle_state=state,
        filled_quantity=filled_quantity,
        average_fill_price=500.0 if filled_quantity else None,
        created_at=NOW,
        updated_at=NOW,
    )


def test_missing_order_state_is_empty(tmp_path: Path) -> None:
    store = JsonOrderStateStore(tmp_path / "orders.json")

    assert store.load_all() == ()
    assert store.list_unresolved() == ()


def test_order_state_round_trip_and_lookup(tmp_path: Path) -> None:
    path = tmp_path / "orders.json"
    store = JsonOrderStateStore(path)
    first = intent()
    second = intent("intent-2", "client-2")

    store.save(second)
    store.save(first)

    assert store.load_all() == (first, second)
    assert store.get_by_intent_id("intent-1") == first
    assert store.get_by_client_order_id("client-2") == second
    assert not path.with_suffix(".json.tmp").exists()


def test_serialization_is_deterministic(tmp_path: Path) -> None:
    path = tmp_path / "orders.json"
    store = JsonOrderStateStore(path)
    store.save(intent("z-intent", "z-client"))
    store.save(intent("a-intent", "a-client"))
    first_contents = path.read_text(encoding="utf-8")

    store.save(intent("a-intent", "a-client"))

    assert path.read_text(encoding="utf-8") == first_contents


def test_failed_replace_leaves_previous_state_intact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "orders.json"
    store = JsonOrderStateStore(path)
    store.save(intent())
    original = path.read_text(encoding="utf-8")

    def fail_replace(self, target):
        del self, target
        raise OSError("simulated atomic replacement failure")

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(OSError, match="replacement failure"):
        store.save(
            replace(
                intent(),
                lifecycle_state=OrderLifecycleState.SUBMITTING,
            )
        )

    assert path.read_text(encoding="utf-8") == original


def test_unresolved_listing_excludes_terminal_state(
    tmp_path: Path,
) -> None:
    store = JsonOrderStateStore(tmp_path / "orders.json")
    store.save(intent())
    store.save(
        intent(
            "filled-intent",
            "filled-client",
            OrderLifecycleState.FILLED,
        )
    )

    assert store.list_unresolved() == (intent(),)


@pytest.mark.parametrize(
    "payload, message",
    [
        ("not-json", "could not be read"),
        (
            json.dumps({"version": 99, "intents": []}),
            "Unsupported order-state version",
        ),
    ],
)
def test_invalid_order_state_file_fails(
    tmp_path: Path,
    payload: str,
    message: str,
) -> None:
    path = tmp_path / "orders.json"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(OrderStateError, match=message):
        JsonOrderStateStore(path).load_all()


def test_invalid_lifecycle_and_timestamp_fail(
    tmp_path: Path,
) -> None:
    path = tmp_path / "orders.json"
    store = JsonOrderStateStore(path)
    store.save(intent())
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["intents"][0]["lifecycle_state"] = "mystery"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(OrderStateError):
        store.load_all()

    payload["intents"][0]["lifecycle_state"] = "created"
    payload["intents"][0]["updated_at"] = "not-a-time"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(OrderStateError, match="updated_at"):
        store.load_all()


def test_invalid_quantities_fail() -> None:
    with pytest.raises(OrderStateError, match="requested_quantity"):
        replace(intent(), requested_quantity=0)

    with pytest.raises(OrderStateError, match="filled_quantity"):
        replace(intent(), filled_quantity=3.0)

    with pytest.raises(OrderStateError, match="partially filled"):
        replace(
            intent(),
            lifecycle_state=OrderLifecycleState.PARTIALLY_FILLED,
        )


def test_saved_intent_identity_fields_cannot_change(tmp_path: Path) -> None:
    store = JsonOrderStateStore(tmp_path / "orders.json")
    store.save(intent())

    with pytest.raises(OrderStateError, match="identity fields"):
        store.save(replace(intent(), requested_quantity=3))


@pytest.mark.parametrize(
    "field_name, value",
    [
        ("requested_quantity", True),
        ("requested_quantity", 1.5),
        ("timeframe_minutes", False),
    ],
)
def test_json_integer_fields_are_strict(
    tmp_path: Path,
    field_name: str,
    value: object,
) -> None:
    path = tmp_path / "orders.json"
    store = JsonOrderStateStore(path)
    store.save(intent())
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["intents"][0][field_name] = value
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(OrderStateError, match=field_name):
        store.load_all()


@pytest.mark.parametrize("field_name", ["intent_id", "client_order_id"])
def test_duplicate_order_identity_in_file_fails(
    tmp_path: Path,
    field_name: str,
) -> None:
    path = tmp_path / "orders.json"
    store = JsonOrderStateStore(path)
    store.save(intent())
    payload = json.loads(path.read_text(encoding="utf-8"))
    duplicate = dict(payload["intents"][0])
    duplicate["intent_id"] = "intent-2"
    duplicate["client_order_id"] = "client-2"
    duplicate[field_name] = payload["intents"][0][field_name]
    payload["intents"].append(duplicate)
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(OrderStateError, match="Duplicate"):
        store.load_all()
