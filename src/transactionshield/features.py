"""Stage 4C: strictly earlier-step, unlabelled behavioural feature replay."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, fields
from decimal import (
    MAX_EMAX, MIN_EMIN, Context, Decimal, DivisionByZero, Inexact,
    InvalidOperation, Overflow, ROUND_HALF_EVEN, localcontext,
)
from uuid import UUID

from transactionshield.canonical import CanonicalTransaction
from transactionshield.contracts import TRANSACTION_TYPES, is_primary_model_eligible

FEATURE_CONTRACT_VERSION = "transactionshield.point-in-time.v1"


def _finite_decimal(value: Decimal, name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal, never a float")


@dataclass(frozen=True, slots=True)
class BehaviouralEvent:
    """The ONLY event accepted by history: no targets, balances or lineage."""

    step: int
    transaction_type: str
    amount: Decimal
    initiator_id: str
    recipient_id: str

    def __post_init__(self) -> None:
        if type(self.step) is not int or not 0 <= self.step <= 2**31 - 1:
            raise ValueError("step must be a non-negative canonical INTEGER")
        if self.transaction_type not in TRANSACTION_TYPES:
            raise ValueError("unexpected canonical transaction type")
        _finite_decimal(self.amount, "amount")
        if self.amount <= 0:
            raise ValueError("amount must be positive")
        for name in ("initiator_id", "recipient_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value.isspace():
                raise ValueError(f"{name} must be nonempty opaque text")


def behavioural_event(row: CanonicalTransaction) -> BehaviouralEvent:
    """Explicit allowlist projection; never hand a canonical object to history."""

    return BehaviouralEvent(row.step, row.transaction_type, row.amount,
                            row.initiator_id, row.recipient_id)


def exact_amount_sum(left: Decimal, right: Decimal) -> Decimal:
    """Align decimal places and reserve a carry digit; trap any loss of precision."""

    _finite_decimal(left, "left amount")
    _finite_decimal(right, "right amount")
    lowest_place = min(left.as_tuple().exponent, right.as_tuple().exponent)
    highest_place = max(left.adjusted(), right.adjusted())
    precision = max(1, highest_place - lowest_place + 2)
    context = Context(prec=precision, rounding=ROUND_HALF_EVEN,
                      Emin=MIN_EMIN, Emax=MAX_EMAX, clamp=0,
                      traps=[Inexact, InvalidOperation, Overflow])
    with localcontext(context) as arithmetic:
        return arithmetic.add(left, right)


def historical_amount_mean(total: Decimal, count: int) -> Decimal | None:
    """Derived means only: explicit 28 significant digits, HALF_EVEN, no quantize."""

    _finite_decimal(total, "historical total")
    if type(count) is not int or count < 0:
        raise ValueError("historical count must be a non-negative integer")
    if count == 0:
        return None
    context = Context(prec=28, rounding=ROUND_HALF_EVEN,
                      Emin=MIN_EMIN, Emax=MAX_EMAX, clamp=0,
                      traps=[InvalidOperation, DivisionByZero, Overflow])
    with localcontext(context) as arithmetic:
        return arithmetic.divide(total, Decimal(count))


@dataclass(frozen=True, slots=True)
class CoreFeatures:
    amount: Decimal
    initiator_prior_outgoing_count: int
    initiator_prior_outgoing_transfer_count: int
    initiator_prior_outgoing_amount_total: Decimal
    initiator_prior_outgoing_amount_mean: Decimal | None
    initiator_prior_outgoing_amount_max: Decimal | None
    recipient_prior_incoming_count: int
    initiator_prior_distinct_recipient_count: int
    recipient_prior_distinct_initiator_count: int


CORE_FEATURE_NAMES = tuple(item.name for item in fields(CoreFeatures))
ENHANCED_ADDITIONAL_NAMES = ("initiator_balance_before", "recipient_balance_before")


@dataclass(frozen=True, slots=True)
class EnhancedFeatures:
    """Current platform-state projection, never an input to behavioural history."""

    core: CoreFeatures
    initiator_balance_before: Decimal
    recipient_balance_before: Decimal

    def __post_init__(self) -> None:
        _finite_decimal(self.initiator_balance_before, "initiator_balance_before")
        _finite_decimal(self.recipient_balance_before, "recipient_balance_before")


@dataclass(frozen=True, slots=True)
class FeatureLineage:
    transaction_id: UUID
    artifact_id: UUID
    source_row_number: int
    step: int


@dataclass(frozen=True, slots=True)
class FeatureExample:
    """Separate metadata and predictor objects; target remains outside this adapter."""

    lineage: FeatureLineage
    core: CoreFeatures
    enhanced: EnhancedFeatures | None


@dataclass(slots=True)
class _Outgoing:
    count: int = 0
    transfer_count: int = 0
    total: Decimal = Decimal(0)
    maximum: Decimal | None = None
    distinct_recipients: int = 0

    def add(self, amount: Decimal, transfer_count: int, count: int = 1,
            maximum: Decimal | None = None) -> None:
        self.total = exact_amount_sum(self.total, amount)
        self.count += count
        self.transfer_count += transfer_count
        candidate = amount if maximum is None else maximum
        self.maximum = candidate if self.maximum is None else max(self.maximum, candidate)


@dataclass(slots=True)
class _Incoming:
    count: int = 0
    distinct_initiators: int = 0


class HistoryEngine:
    """Two-phase replay with aggregate pending state and one exact set of pairs.

    A strictly increasing step commits the previous complete step. finish() commits
    the last step after successful EOF. Abort makes a failed replay unusable.
    No event objects are retained. Memory grows with entities/unique pairs, not
    repeated transactions; distinct pairs can still grow in the worst case.
    """

    def __init__(self) -> None:
        self._outgoing: dict[str, _Outgoing] = {}
        self._incoming: dict[str, _Incoming] = {}
        self._pairs: set[tuple[str, str]] = set()
        self._entity_text: dict[str, str] = {}
        self._pending_outgoing: dict[str, _Outgoing] = {}
        self._pending_incoming: dict[str, int] = {}
        self._pending_pairs: set[tuple[str, str]] = set()
        self._step: int | None = None
        self._committed_rows = 0
        self._pending_rows = 0
        self._closed = False
        self._failed = False

    def _check_active(self) -> None:
        if self._closed or self._failed:
            raise ValueError("history replay is finished or failed; create a new engine")

    def _commit_pending(self) -> None:
        for entity, delta in self._pending_outgoing.items():
            total = self._outgoing.setdefault(entity, _Outgoing())
            total.add(delta.total, delta.transfer_count, delta.count, delta.maximum)
        for entity, count in self._pending_incoming.items():
            self._incoming.setdefault(entity, _Incoming()).count += count
        for initiator, recipient in self._pending_pairs:
            self._outgoing[initiator].distinct_recipients += 1
            self._incoming[recipient].distinct_initiators += 1
        self._pairs.update(self._pending_pairs)
        self._committed_rows += self._pending_rows
        self._clear_pending()

    def _clear_pending(self) -> None:
        self._pending_outgoing.clear()
        self._pending_incoming.clear()
        self._pending_pairs.clear()
        self._pending_rows = 0

    def process(self, event: BehaviouralEvent) -> CoreFeatures | None:
        self._check_active()
        try:
            # Reject richer duck-typed objects/subclasses carrying forbidden fields.
            if type(event) is not BehaviouralEvent:
                raise TypeError("history accepts only the narrow BehaviouralEvent type")
            if self._step is not None and event.step < self._step:
                raise ValueError(f"chronological regression: {event.step} follows {self._step}")
            if self._step is not None and event.step > self._step:
                self._commit_pending()
            self._step = event.step
            result = self._calculate(event) if is_primary_model_eligible(event.transaction_type) else None
            initiator = self._entity_text.setdefault(event.initiator_id, event.initiator_id)
            recipient = self._entity_text.setdefault(event.recipient_id, event.recipient_id)
            delta = self._pending_outgoing.setdefault(initiator, _Outgoing())
            delta.add(event.amount, int(is_primary_model_eligible(event.transaction_type)))
            self._pending_incoming[recipient] = self._pending_incoming.get(recipient, 0) + 1
            pair = (initiator, recipient)
            if pair not in self._pairs:
                self._pending_pairs.add(pair)
            self._pending_rows += 1
            return result
        except Exception:
            self.abort()
            raise

    def _calculate(self, event: BehaviouralEvent) -> CoreFeatures:
        outgoing = self._outgoing.get(event.initiator_id, _Outgoing())
        incoming = self._incoming.get(event.recipient_id, _Incoming())
        return CoreFeatures(
            event.amount, outgoing.count, outgoing.transfer_count, outgoing.total,
            historical_amount_mean(outgoing.total, outgoing.count), outgoing.maximum,
            incoming.count, outgoing.distinct_recipients, incoming.distinct_initiators,
        )

    def finish(self) -> None:
        self._check_active()
        try:
            self._commit_pending()
            self._closed = True
        except Exception:
            self.abort()
            raise

    def abort(self) -> None:
        self._clear_pending()
        self._failed = True

    def state_statistics(self) -> dict[str, int]:
        """Diagnostics only; never predictors and never historical-event storage."""

        return {
            "committed_rows": self._committed_rows,
            "pending_rows": self._pending_rows,
            "initiator_entities": len(self._outgoing),
            "recipient_entities": len(self._incoming),
            "distinct_pairs": len(self._pairs),
            "interned_entity_strings": len(self._entity_text),
            "pending_initiator_entities": len(self._pending_outgoing),
            "pending_recipient_entities": len(self._pending_incoming),
            "pending_new_pairs": len(self._pending_pairs),
        }


def iter_feature_examples(
    rows: Iterable[CanonicalTransaction], *, enhanced: bool = False,
    engine: HistoryEngine | None = None,
) -> Iterator[FeatureExample]:
    """Project canonical rows, emit only transfers, and finish only on successful EOF.

    Streamed examples are provisional until complete consumption. Any parsing
    failure or early close aborts pending state; no final dataset is published.
    """

    history = engine if engine is not None else HistoryEngine()
    complete = False
    try:
        for row in rows:
            core = history.process(behavioural_event(row))
            if core is not None:
                platform = (EnhancedFeatures(core, row.initiator_balance_before,
                                             row.recipient_balance_before) if enhanced else None)
                yield FeatureExample(
                    FeatureLineage(row.transaction_id, row.artifact_id, row.source_row_number, row.step),
                    core, platform,
                )
        history.finish()
        complete = True
    finally:
        if not complete:
            history.abort()
