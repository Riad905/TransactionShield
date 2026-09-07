"""Strict, lossless canonical parsing; deliberately separate from inspection."""

from __future__ import annotations

import csv
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import NoReturn, TextIO
from uuid import UUID, uuid5

from transactionshield.contracts import (
    NUMERIC_CONTRACT_COLUMNS,
    TRANSACTION_ID_NAMESPACE,
    TRANSACTION_TYPES,
    deterministic_transaction_id,
    parse_plain_decimal,
    validate_source_row_number,
)
from transactionshield.ingestion import MOMTSIM_PAPER_DATASET_V1_COLUMNS

SCHEMA_VERSION = "transactionshield.canonical.v1"
# Ordered schema: role is descriptive, not a feature-selection implementation.
CANONICAL_SCHEMA = (
    ("transaction_id", "UUID", "lineage"),
    ("artifact_id", "UUID", "lineage"),
    ("source_row_number", "BIGINT", "lineage"),
    ("step", "INTEGER", "temporal_metadata"),
    ("transaction_type", "TEXT", "source"),
    ("amount", "NUMERIC", "source"),
    ("initiator_id", "TEXT", "entity_key"),
    ("initiator_balance_before", "NUMERIC", "source"),
    ("initiator_balance_after", "NUMERIC", "post_event_not_predictive"),
    ("recipient_id", "TEXT", "entity_key"),
    ("recipient_balance_before", "NUMERIC", "source"),
    ("recipient_balance_after", "NUMERIC", "post_event_not_predictive"),
    ("is_fraud", "SMALLINT", "target_not_predictive"),
)
CANONICAL_COLUMNS = tuple(field[0] for field in CANONICAL_SCHEMA)


class CanonicalValidationError(ValueError):
    """A source record violates the strict canonical contract."""


@dataclass(frozen=True, slots=True)
class CanonicalTransaction:
    transaction_id: UUID
    artifact_id: UUID
    source_row_number: int
    step: int
    transaction_type: str
    amount: Decimal
    initiator_id: str
    initiator_balance_before: Decimal
    initiator_balance_after: Decimal
    recipient_id: str
    recipient_balance_before: Decimal
    recipient_balance_after: Decimal
    is_fraud: int
    # Retaining lexemes also preserves plus signs, leading zeros and decimal scale.
    # Decimal values remain the typed representation; neither representation rounds.
    monetary_literals: tuple[str, ...]

    def csv_values(self) -> tuple[object, ...]:
        amount, old_i, new_i, old_r, new_r = self.monetary_literals
        return (
            str(self.transaction_id), str(self.artifact_id), self.source_row_number,
            self.step, self.transaction_type, amount, self.initiator_id, old_i,
            new_i, self.recipient_id, old_r, new_r, self.is_fraud,
        )


def parse_canonical_row(
    values: Sequence[str], source_row_number: int, artifact_sha256: str
) -> CanonicalTransaction:
    """Validate every source field, preserving opaque text and monetary lexemes."""

    validate_source_row_number(source_row_number)
    transaction_id = deterministic_transaction_id(artifact_sha256, source_row_number)

    def fail(column: str, reason: str) -> NoReturn:
        raise CanonicalValidationError(f"CSV row {source_row_number}, {column}: {reason}")

    if len(values) != len(MOMTSIM_PAPER_DATASET_V1_COLUMNS):
        fail("record", f"expected 10 fields, received {len(values)}")
    row = dict(zip(MOMTSIM_PAPER_DATASET_V1_COLUMNS, values, strict=True))
    for column, value in row.items():
        if not isinstance(value, str):
            fail(column, "expected source text")
    if re.fullmatch(r"[+-]?[0-9]+", row["step"]) is None:
        fail("step", "expected a non-negative integer literal")
    try:
        step = int(row["step"])
    except ValueError as error:
        fail("step", str(error))
    if not 0 <= step <= 2**31 - 1:
        fail("step", "outside non-negative canonical PostgreSQL INTEGER range")
    if row["transactionType"] not in TRANSACTION_TYPES:
        fail("transactionType", f"unexpected value {row['transactionType']!r}")
    if row["isFraud"] not in {"0", "1"}:
        fail("isFraud", f"unexpected value {row['isFraud']!r}")
    for column in ("initiator", "recipient"):
        if not row[column] or row[column].isspace():
            fail(column, "identifier must not be empty or whitespace-only")
    numbers = []
    for column in NUMERIC_CONTRACT_COLUMNS:
        try:
            numbers.append(parse_plain_decimal(row[column]))
        except ValueError as error:
            fail(column, str(error))
    amount, old_i, new_i, old_r, new_r = numbers
    if amount <= 0:
        fail("amount", "must be positive")
    return CanonicalTransaction(
        transaction_id, uuid5(TRANSACTION_ID_NAMESPACE, artifact_sha256),
        source_row_number, step, row["transactionType"], amount, row["initiator"],
        old_i, new_i, row["recipient"], old_r, new_r, int(row["isFraud"]),
        tuple(row[column] for column in NUMERIC_CONTRACT_COLUMNS),
    )


def iter_canonical_records(
    source: TextIO, artifact_sha256: str
) -> Iterator[CanonicalTransaction]:
    """Read exact ordered headers and strict CSV records with logical row context."""

    reader = csv.reader(source, strict=True)
    row_number = 1
    try:
        header = next(reader, None)
        if header != list(MOMTSIM_PAPER_DATASET_V1_COLUMNS):
            raise CanonicalValidationError("CSV row 1, header: exact source sequence required")
        row_number = 2
        for values in reader:
            yield parse_canonical_row(values, row_number, artifact_sha256)
            row_number += 1
    except (csv.Error, UnicodeError) as error:
        raise CanonicalValidationError(
            f"CSV row {row_number}, record/encoding: {error}"
        ) from error
