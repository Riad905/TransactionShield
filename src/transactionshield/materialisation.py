"""Deterministic canonical CSV/JSON serialisation and read-back verification."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import BinaryIO

from transactionshield.audit import sha256_file
from transactionshield.canonical import (
    CANONICAL_COLUMNS, CanonicalTransaction, parse_canonical_row,
)
from transactionshield.validation import ArtifactContract, IntegrityError, Reconciliation

SERIALISATION = {
    "encoding": "utf-8",
    "bom": False,
    "newline": "LF",
    "delimiter": ",",
    "quotechar": '"',
    "quoting": "minimal",
    "ordering": "source_row_number ascending; no within-step event-order claim",
    "monetary_rendering": "exact validated source plain-decimal lexeme",
    "nulls": "not allowed in canonical source fields",
    "population": "all source transaction types; no feature construction",
}


class _Utf8HashWriter:
    def __init__(self, destination: BinaryIO) -> None:
        self.destination = destination
        self.digest = hashlib.sha256()
        self.byte_size = 0

    def write(self, value: str) -> int:
        encoded = value.encode("utf-8")
        self.destination.write(encoded)
        self.digest.update(encoded)
        self.byte_size += len(encoded)
        return len(value)


def write_canonical_csv(
    records: Iterable[CanonicalTransaction], path: Path, counts: Reconciliation
) -> dict[str, object]:
    """Write exclusively to a new incomplete file with a streaming byte digest."""

    with path.open("xb") as binary:
        output = _Utf8HashWriter(binary)
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(CANONICAL_COLUMNS)
        for record in records:
            counts.observe(record)
            writer.writerow(record.csv_values())
    return {"byte_size": output.byte_size, "sha256": output.digest.hexdigest()}


def verify_canonical_csv(
    path: Path, expected_output: dict[str, object], contract: ArtifactContract
) -> Reconciliation:
    """Read back typed rows, exact identities and counts, then verify file bytes."""

    counts = Reconciliation()
    with path.open("r", encoding="utf-8", errors="strict", newline="") as source:
        reader = csv.reader(source, strict=True)
        if next(reader, None) != list(CANONICAL_COLUMNS):
            raise IntegrityError("canonical output header mismatch")
        for row_number, values in enumerate(reader, start=2):
            if len(values) != len(CANONICAL_COLUMNS):
                raise IntegrityError(f"canonical output width mismatch at row {row_number}")
            # Canonical payload after the three lineage fields follows source order.
            record = parse_canonical_row(values[3:], row_number, contract.sha256)
            if values != [str(value) for value in record.csv_values()]:
                raise IntegrityError(f"canonical output lineage/rendering mismatch at row {row_number}")
            counts.observe(record)
    counts.verify(contract)
    if (path.stat().st_size != expected_output["byte_size"]
            or sha256_file(path) != expected_output["sha256"]):
        raise IntegrityError("canonical output bytes differ from the written stream")
    return counts


def write_json(path: Path, content: dict[str, object]) -> None:
    """Stable JSON bytes without platform newline translation or volatile fields."""

    with path.open("xb") as output:
        output.write((json.dumps(content, indent=2, sort_keys=True,
                                 ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"))
