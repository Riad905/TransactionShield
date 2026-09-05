"""Minimal CSV ingestion conventions for TransactionShield Stage 1.

This module validates structural preconditions only. Value coercion, business-rule
validation, database loading, and feature engineering are deliberately future work.
"""

from __future__ import annotations

import csv
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

# Schema published for the paper's dataset version 1. This name does not refer
# to the independent version number of the Mendeley repository release.
MOMTSIM_PAPER_DATASET_V1_COLUMNS: tuple[str, ...] = (
    "step",
    "transactionType",
    "amount",
    "initiator",
    "oldBalInitiator",
    "newBalInitiator",
    "recipient",
    "oldBalRecipient",
    "newBalRecipient",
    "isFraud",
)


class CsvSchemaError(ValueError):
    """Raised when a CSV file does not satisfy the required header contract."""


@dataclass(frozen=True, slots=True)
class CsvSchemaReport:
    """Result of inspecting a CSV header without scanning its data rows."""

    path: Path
    columns: tuple[str, ...]
    extra_columns: tuple[str, ...]


def inspect_csv(
    path: str | Path,
    required_columns: Sequence[str] = MOMTSIM_PAPER_DATASET_V1_COLUMNS,
) -> CsvSchemaReport:
    """Validate a CSV header and return its observed structural metadata.

    Column matching is intentionally case-sensitive. Extra columns are reported but
    accepted, allowing a documented dataset revision to be inspected before support
    is added explicitly.
    """

    csv_path = Path(path)
    if not csv_path.is_file():
        raise FileNotFoundError(f"CSV file does not exist: {csv_path}")

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            raw_header = next(reader)
        except StopIteration as error:
            raise CsvSchemaError(f"CSV file is empty: {csv_path}") from error

    columns = tuple(column.strip() for column in raw_header)
    if not columns or any(not column for column in columns):
        raise CsvSchemaError("CSV header contains an empty column name")

    duplicates = tuple(
        column for column, count in Counter(columns).items() if count > 1
    )
    if duplicates:
        duplicate_list = ", ".join(duplicates)
        raise CsvSchemaError(f"CSV header contains duplicate columns: {duplicate_list}")

    required = tuple(required_columns)
    missing = tuple(column for column in required if column not in columns)
    if missing:
        missing_list = ", ".join(missing)
        raise CsvSchemaError(f"CSV header is missing required columns: {missing_list}")

    required_set = set(required)
    extras = tuple(column for column in columns if column not in required_set)
    return CsvSchemaReport(path=csv_path, columns=columns, extra_columns=extras)


def iter_csv_rows(
    path: str | Path,
    required_columns: Sequence[str] = MOMTSIM_PAPER_DATASET_V1_COLUMNS,
) -> Iterator[dict[str, str]]:
    """Yield CSV rows lazily after applying the header contract.

    Values remain strings so this Stage 1 interface cannot imply that semantic or
    type validation has already occurred.
    """

    csv_path = Path(path)
    report = inspect_csv(csv_path, required_columns)

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        next(reader)  # The header was already validated by inspect_csv.
        for row_number, values in enumerate(reader, start=2):
            if len(values) != len(report.columns):
                raise CsvSchemaError(
                    f"CSV row {row_number} has {len(values)} fields; "
                    f"expected {len(report.columns)}"
                )
            yield dict(zip(report.columns, values, strict=True))
