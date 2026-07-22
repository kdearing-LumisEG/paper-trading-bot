"""Fail-closed reconciliation of broker and local execution state."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
import json
import math
from pathlib import Path
from typing import Callable, Protocol

from trading_bot.broker.models import (
    AccountSnapshot,
    BrokerOrder,
    PositionSnapshot,
)
from trading_bot.execution.position_state import (
    PositionPhase,
    PositionStateStore,
    TrackedPosition,
)
from trading_bot.execution.order_state import (
    NullOrderStateStore,
    OrderIntent,
    OrderStateError,
    OrderStateStore,
)
from trading_bot.execution.service import (
    PaperExecutionService,
)


class ReconciliationIssueCode(str, Enum):
    """Machine-readable reasons that reconciliation is unsafe."""

    ACCOUNT_BLOCKED = "account_blocked"
    TRADING_BLOCKED = "trading_blocked"
    OPEN_ORDER = "open_order"
    UNEXPECTED_POSITION = "unexpected_position"
    MULTIPLE_SYMBOL_POSITIONS = "multiple_symbol_positions"
    SHORT_POSITION = "short_position"
    FRACTIONAL_POSITION = "fractional_position"
    UNTRACKED_POSITION = "untracked_position"
    MISSING_BROKER_POSITION = "missing_broker_position"
    POSITION_QUANTITY_MISMATCH = "position_quantity_mismatch"
    AVERAGE_ENTRY_PRICE_MISMATCH = "average_entry_price_mismatch"
    INVALID_TRACKED_POSITION = "invalid_tracked_position"
    ADOPTION_NOT_ALLOWED = "adoption_not_allowed"
    UNRESOLVED_ORDER_INTENT = "unresolved_order_intent"
    ORDER_INTENT_MISMATCH = "order_intent_mismatch"
    LEGACY_OPEN_POSITION = "legacy_open_position"
    POSITION_GENERATION_MISMATCH = (
        "position_generation_mismatch"
    )
    ORDER_STATE_INVALID = "order_state_invalid"


@dataclass(frozen=True)
class ReconciliationIssue:
    """One operational mismatch discovered during reconciliation."""

    code: ReconciliationIssueCode
    message: str
    symbol: str | None = None
    order_id: str | None = None
    client_order_id: str | None = None


@dataclass(frozen=True)
class ReconciliationReport:
    """Auditable broker-versus-local reconciliation result."""

    checked_at: datetime
    symbol: str
    safe: bool
    adopted: bool
    account: AccountSnapshot
    broker_positions: list[PositionSnapshot]
    open_orders: list[BrokerOrder]
    tracked_position: TrackedPosition | None
    issues: list[ReconciliationIssue]
    matched_order_intents: list[str] = field(
        default_factory=list
    )
    advanced_order_intents: list[str] = field(
        default_factory=list
    )
    unresolved_order_intents: list[str] = field(
        default_factory=list
    )
    unknown_broker_orders: list[BrokerOrder] = field(
        default_factory=list
    )
    position_generation_status: str = "not_applicable"

    @property
    def issue_codes(self) -> list[str]:
        """Return issue codes in report order."""

        return [
            issue.code.value
            for issue in self.issues
        ]


class ReconciliationLogger(Protocol):
    """Destination for completed reconciliation reports."""

    def log(
        self,
        report: ReconciliationReport,
    ) -> None:
        """Persist one reconciliation report."""


class NullReconciliationLogger:
    """Discard reconciliation reports."""

    def log(
        self,
        report: ReconciliationReport,
    ) -> None:
        del report


class JsonlReconciliationLogger:
    """Append one JSON document per reconciliation check."""

    def __init__(
        self,
        path: Path,
    ) -> None:
        self._path = path

    @staticmethod
    def _json_default(
        value: object,
    ) -> object:
        if isinstance(value, Enum):
            return value.value

        if isinstance(
            value,
            (
                date,
                datetime,
            ),
        ):
            return value.isoformat()

        raise TypeError(
            f"Object of type {type(value).__name__} "
            "is not JSON serializable."
        )

    def log(
        self,
        report: ReconciliationReport,
    ) -> None:
        self._path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self._path.open(
            "a",
            encoding="utf-8",
        ) as handle:
            json.dump(
                asdict(report),
                handle,
                default=self._json_default,
                sort_keys=True,
            )
            handle.write("\n")


def _is_whole_number(
    value: float,
) -> bool:
    return (
        math.isfinite(value)
        and value >= 0
        and float(value).is_integer()
    )


class ReconciliationService:
    """Compare broker truth with strategy-owned local state."""

    def __init__(
        self,
        *,
        execution_service: PaperExecutionService,
        position_state_store: PositionStateStore,
        symbol: str,
        average_price_tolerance: float = 0.01,
        logger: ReconciliationLogger | None = None,
        order_state_store: OrderStateStore | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        normalized_symbol = symbol.strip().upper()

        if not normalized_symbol:
            raise ValueError(
                "symbol cannot be empty."
            )

        if (
            not math.isfinite(
                average_price_tolerance
            )
            or average_price_tolerance < 0
        ):
            raise ValueError(
                "average_price_tolerance must be finite "
                "and nonnegative."
            )

        self._execution_service = execution_service
        self._position_state_store = (
            position_state_store
        )
        self._order_state_store = (
            order_state_store
            if order_state_store is not None
            else NullOrderStateStore()
        )
        self._symbol = normalized_symbol
        self._average_price_tolerance = (
            average_price_tolerance
        )
        self._logger = (
            logger
            if logger is not None
            else NullReconciliationLogger()
        )
        self._now = (
            now
            if now is not None
            else lambda: datetime.now(
                timezone.utc
            )
        )

    def _configured_positions(
        self,
        positions: list[PositionSnapshot],
    ) -> list[PositionSnapshot]:
        return [
            position
            for position in positions
            if position.symbol.strip().upper()
            == self._symbol
        ]

    def _base_issues(
        self,
        *,
        account: AccountSnapshot,
        positions: list[PositionSnapshot],
        open_orders: list[BrokerOrder],
    ) -> list[ReconciliationIssue]:
        issues: list[
            ReconciliationIssue
        ] = []

        if account.account_blocked:
            issues.append(
                ReconciliationIssue(
                    code=(
                        ReconciliationIssueCode
                        .ACCOUNT_BLOCKED
                    ),
                    message=(
                        "The paper account is blocked."
                    ),
                )
            )

        if account.trading_blocked:
            issues.append(
                ReconciliationIssue(
                    code=(
                        ReconciliationIssueCode
                        .TRADING_BLOCKED
                    ),
                    message=(
                        "Trading is blocked for the "
                        "paper account."
                    ),
                )
            )

        for order in open_orders:
            issues.append(
                ReconciliationIssue(
                    code=(
                        ReconciliationIssueCode
                        .OPEN_ORDER
                    ),
                    message=(
                        "An unresolved broker order exists."
                    ),
                    symbol=order.symbol,
                    order_id=order.order_id,
                    client_order_id=(
                        order.client_order_id
                    ),
                )
            )

        for position in positions:
            normalized_symbol = (
                position.symbol.strip().upper()
            )

            if normalized_symbol != self._symbol:
                issues.append(
                    ReconciliationIssue(
                        code=(
                            ReconciliationIssueCode
                            .UNEXPECTED_POSITION
                        ),
                        message=(
                            "A broker position exists outside "
                            "the configured strategy symbol."
                        ),
                        symbol=normalized_symbol,
                    )
                )

        configured_positions = (
            self._configured_positions(
                positions
            )
        )

        if len(configured_positions) > 1:
            issues.append(
                ReconciliationIssue(
                    code=(
                        ReconciliationIssueCode
                        .MULTIPLE_SYMBOL_POSITIONS
                    ),
                    message=(
                        "The broker returned multiple positions "
                        f"for {self._symbol}."
                    ),
                    symbol=self._symbol,
                )
            )

        for position in configured_positions:
            if (
                not math.isfinite(
                    position.quantity
                )
                or position.quantity < 0
            ):
                issues.append(
                    ReconciliationIssue(
                        code=(
                            ReconciliationIssueCode
                            .SHORT_POSITION
                        ),
                        message=(
                            "A short or invalid position is not "
                            "supported by this strategy."
                        ),
                        symbol=self._symbol,
                    )
                )
            elif not float(position.quantity).is_integer():
                issues.append(
                    ReconciliationIssue(
                        code=(
                            ReconciliationIssueCode
                            .FRACTIONAL_POSITION
                        ),
                        message=(
                            "A fractional broker position is not "
                            "supported by this strategy."
                        ),
                        symbol=self._symbol,
                    )
                )

        return issues

    def _comparison_issues(
        self,
        *,
        broker_position: PositionSnapshot | None,
        tracked_position: TrackedPosition | None,
    ) -> list[ReconciliationIssue]:
        issues: list[
            ReconciliationIssue
        ] = []

        broker_quantity = (
            broker_position.quantity
            if broker_position is not None
            else 0.0
        )

        if tracked_position is None:
            if broker_quantity > 0:
                issues.append(
                    ReconciliationIssue(
                        code=(
                            ReconciliationIssueCode
                            .UNTRACKED_POSITION
                        ),
                        message=(
                            "The broker has a position that is "
                            "not present in local strategy state."
                        ),
                        symbol=self._symbol,
                    )
                )

            return issues

        if (
            tracked_position.legacy_open
            or (
                tracked_position.quantity > 0
                and not tracked_position
                .position_generation_id
            )
        ):
            issues.append(
                ReconciliationIssue(
                    code=(
                        ReconciliationIssueCode
                        .LEGACY_OPEN_POSITION
                    ),
                    message=(
                        "An open legacy position lacks generation "
                        "metadata and cannot be upgraded automatically."
                    ),
                    symbol=self._symbol,
                )
            )
            return issues

        if tracked_position.phase is (
            PositionPhase.RECONCILIATION_REQUIRED
        ):
            issues.append(
                ReconciliationIssue(
                    code=(
                        ReconciliationIssueCode
                        .POSITION_GENERATION_MISMATCH
                    ),
                    message=(
                        "Local position ownership requires reconciliation."
                    ),
                    symbol=self._symbol,
                )
            )
            return issues

        if not _is_whole_number(
            tracked_position.quantity
        ):
            issues.append(
                ReconciliationIssue(
                    code=(
                        ReconciliationIssueCode
                        .INVALID_TRACKED_POSITION
                    ),
                    message=(
                        "Local tracked quantity is not a "
                        "nonnegative whole-share value."
                    ),
                    symbol=self._symbol,
                )
            )
            return issues

        tracked_quantity = (
            tracked_position.quantity
        )

        if (
            tracked_quantity > 0
            and broker_quantity == 0
        ):
            issues.append(
                ReconciliationIssue(
                    code=(
                        ReconciliationIssueCode
                        .MISSING_BROKER_POSITION
                    ),
                    message=(
                        "Local state expects an open position, "
                        "but the broker is flat."
                    ),
                    symbol=self._symbol,
                )
            )
            return issues

        if (
            tracked_quantity
            != broker_quantity
        ):
            issues.append(
                ReconciliationIssue(
                    code=(
                        ReconciliationIssueCode
                        .POSITION_QUANTITY_MISMATCH
                    ),
                    message=(
                        "Broker and local position quantities "
                        "do not match."
                    ),
                    symbol=self._symbol,
                )
            )
            return issues

        if (
            broker_position is not None
            and tracked_quantity > 0
        ):
            tracked_average = (
                tracked_position
                .average_entry_price
            )

            broker_average = (
                broker_position
                .average_entry_price
            )

            if (
                tracked_average is None
                or not math.isfinite(
                    tracked_average
                )
                or not math.isfinite(
                    broker_average
                )
                or abs(
                    tracked_average
                    - broker_average
                )
                > self._average_price_tolerance
            ):
                issues.append(
                    ReconciliationIssue(
                        code=(
                            ReconciliationIssueCode
                            .AVERAGE_ENTRY_PRICE_MISMATCH
                        ),
                        message=(
                            "Broker and local average entry "
                            "prices do not match within tolerance."
                        ),
                        symbol=self._symbol,
                    )
                )

        return issues

    def _can_adopt(
        self,
        *,
        account: AccountSnapshot,
        positions: list[PositionSnapshot],
        open_orders: list[BrokerOrder],
    ) -> bool:
        if (
            account.account_blocked
            or account.trading_blocked
            or open_orders
        ):
            return False

        if any(
            position.symbol.strip().upper()
            != self._symbol
            for position in positions
        ):
            return False

        configured_positions = (
            self._configured_positions(
                positions
            )
        )

        if len(configured_positions) > 1:
            return False

        if not configured_positions:
            return True

        # Open-position adoption/upgrade is explicitly outside this package.
        return False

    def _reconcile_order_intents(
        self,
        *,
        intents: tuple[OrderIntent, ...],
        open_orders: list[BrokerOrder],
    ) -> tuple[
        list[str],
        list[str],
        list[str],
        list[BrokerOrder],
        list[ReconciliationIssue],
    ]:
        matched: list[str] = []
        advanced_ids: list[str] = []
        unresolved: list[str] = []
        issues: list[ReconciliationIssue] = []
        matched_order_ids: set[str] = set()

        for intent in intents:
            if intent.lifecycle_state.is_terminal:
                continue

            matches = [
                order
                for order in open_orders
                if order.client_order_id
                == intent.client_order_id
            ]

            if len(matches) > 1:
                unresolved.append(intent.intent_id)
                issues.append(
                    ReconciliationIssue(
                        code=(
                            ReconciliationIssueCode
                            .ORDER_INTENT_MISMATCH
                        ),
                        message=(
                            "Multiple broker orders match one durable intent."
                        ),
                        symbol=intent.symbol,
                        client_order_id=(
                            intent.client_order_id
                        ),
                    )
                )
                continue

            try:
                if matches:
                    broker_order = matches[0]
                    matched_order_ids.add(
                        broker_order.order_id
                    )
                    current = (
                        self._execution_service
                        .reconcile_known_order(
                            intent,
                            broker_order,
                        )
                    )
                else:
                    current = (
                        self._execution_service
                        .reconcile_order_intent(intent)
                    )
            except Exception as exc:
                unresolved.append(intent.intent_id)
                issues.append(
                    ReconciliationIssue(
                        code=(
                            ReconciliationIssueCode
                            .UNRESOLVED_ORDER_INTENT
                        ),
                        message=(
                            "Durable order reconciliation failed: "
                            f"{type(exc).__name__}."
                        ),
                        symbol=intent.symbol,
                        client_order_id=(
                            intent.client_order_id
                        ),
                    )
                )
                continue

            matched.append(intent.intent_id)
            if current != intent:
                advanced_ids.append(intent.intent_id)

            if current.lifecycle_state.is_unresolved:
                unresolved.append(intent.intent_id)
                issues.append(
                    ReconciliationIssue(
                        code=(
                            ReconciliationIssueCode
                            .UNRESOLVED_ORDER_INTENT
                        ),
                        message=(
                            "A durable order intent remains nonterminal "
                            "or uncertain."
                        ),
                        symbol=current.symbol,
                        order_id=current.broker_order_id,
                        client_order_id=(
                            current.client_order_id
                        ),
                    )
                )

        unknown_orders = [
            order
            for order in open_orders
            if order.order_id not in matched_order_ids
        ]
        return (
            matched,
            advanced_ids,
            unresolved,
            unknown_orders,
            issues,
        )

    def run(
        self,
        *,
        adopt_position: bool = False,
    ) -> ReconciliationReport:
        """Run one reconciliation check and optionally adopt broker state."""

        checked_at = self._now()

        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(
                tzinfo=timezone.utc
            )
        else:
            checked_at = checked_at.astimezone(
                timezone.utc
            )

        account = (
            self._execution_service.get_account()
        )
        positions = (
            self._execution_service
            .list_positions()
        )
        open_orders = (
            self._execution_service
            .list_open_orders()
        )

        order_state_issues: list[
            ReconciliationIssue
        ] = []
        try:
            order_intents = (
                self._order_state_store.load_all()
            )
        except OrderStateError:
            order_intents = ()
            order_state_issues.append(
                ReconciliationIssue(
                    code=(
                        ReconciliationIssueCode
                        .ORDER_STATE_INVALID
                    ),
                    message=(
                        "Durable order-state data is invalid and "
                        "was left untouched."
                    ),
                    symbol=self._symbol,
                )
            )

        (
            matched_order_intents,
            advanced_order_intents,
            unresolved_order_intents,
            unknown_broker_orders,
            order_intent_issues,
        ) = self._reconcile_order_intents(
            intents=order_intents,
            open_orders=open_orders,
        )

        adopted = False

        if adopt_position:
            if self._can_adopt(
                account=account,
                positions=positions,
                open_orders=open_orders,
            ) and not (
                order_state_issues
                or order_intent_issues
            ):
                configured_positions = (
                    self._configured_positions(
                        positions
                    )
                )

                if configured_positions:
                    broker_position = (
                        configured_positions[0]
                    )

                    tracked_position = (
                        TrackedPosition(
                            symbol=self._symbol,
                            quantity=(
                                broker_position
                                .quantity
                            ),
                            average_entry_price=(
                                broker_position
                                .average_entry_price
                            ),
                            updated_at=checked_at,
                            adopted=True,
                        )
                    )
                else:
                    tracked_position = (
                        TrackedPosition.flat(
                            symbol=self._symbol,
                            updated_at=checked_at,
                            adopted=True,
                        )
                    )

                self._position_state_store.save(
                    tracked_position
                )
                adopted = True

        tracked_position = (
            self._position_state_store.load(
                self._symbol
            )
        )

        issues = self._base_issues(
            account=account,
            positions=positions,
            open_orders=unknown_broker_orders,
        )
        issues[:0] = (
            order_state_issues
            + order_intent_issues
        )

        configured_positions = (
            self._configured_positions(
                positions
            )
        )

        broker_position = (
            configured_positions[0]
            if len(configured_positions) == 1
            else None
        )

        issues.extend(
            self._comparison_issues(
                broker_position=broker_position,
                tracked_position=tracked_position,
            )
        )

        if adopt_position and not adopted:
            issues.append(
                ReconciliationIssue(
                    code=(
                        ReconciliationIssueCode
                        .ADOPTION_NOT_ALLOWED
                    ),
                    message=(
                        "Broker state could not be adopted while "
                        "other reconciliation blockers exist."
                    ),
                    symbol=self._symbol,
                )
            )

        report = ReconciliationReport(
            checked_at=checked_at,
            symbol=self._symbol,
            safe=not issues,
            adopted=adopted,
            account=account,
            broker_positions=list(
                positions
            ),
            open_orders=list(
                open_orders
            ),
            tracked_position=(
                tracked_position
            ),
            issues=issues,
            matched_order_intents=(
                matched_order_intents
            ),
            advanced_order_intents=(
                advanced_order_intents
            ),
            unresolved_order_intents=(
                unresolved_order_intents
            ),
            unknown_broker_orders=(
                unknown_broker_orders
            ),
            position_generation_status=(
                "legacy_open"
                if (
                    tracked_position is not None
                    and tracked_position.legacy_open
                )
                else (
                    "generation_aware"
                    if (
                        tracked_position is not None
                        and tracked_position
                        .position_generation_id
                    )
                    else "not_applicable"
                )
            ),
        )

        self._logger.log(report)
        return report
