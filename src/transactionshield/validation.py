"""Approved artifact gate and bounded canonical reconciliation."""

from __future__ import annotations

import hashlib
import io
import os
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, TextIO

from transactionshield.canonical import CanonicalTransaction


class IntegrityError(ValueError):
    """Artifact identity, source stability or reconciliation failed."""


@dataclass(frozen=True, slots=True)
class ArtifactContract:
    filename: str
    byte_size: int
    sha256: str
    row_count: int
    legitimate_count: int
    fraud_count: int
    transaction_type_counts: tuple[tuple[str, int], ...]
    step_min: int
    step_max: int
    repository_doi: str
    repository_version: int
    paper_dataset_version: int
    source_url: str
    retrieved_on: str
    source_licence: str


# Stage 2's measured evidence, not inferred from filename or repository version.
APPROVED_ARTIFACT = ArtifactContract(
    filename="synthetic_mobile_money_transaction_dataset.csv",
    byte_size=156_564_413,
    sha256="da951eb95735da96271740a3e66b676b342d3831ce3111cd19dbfa020d3bd0a7",
    row_count=1_720_181,
    legitimate_count=1_544_663,
    fraud_count=175_518,
    transaction_type_counts=(("DEBIT", 5392), ("DEPOSIT", 384431), ("PAYMENT", 667245),
                             ("TRANSFER", 569328), ("WITHDRAWAL", 93785)),
    step_min=0,
    step_max=143,
    repository_doi="10.17632/zhj366m53p.2",
    repository_version=2,
    paper_dataset_version=1,
    source_url="https://data.mendeley.com/datasets/zhj366m53p/2",
    retrieved_on="2026-09-05",
    source_licence="CC BY 4.0",
)


class HashingReader(io.RawIOBase):
    """Hash exactly the binary bytes supplied to the CSV decoder."""

    def __init__(self, source: BinaryIO) -> None:
        super().__init__()
        self.source = source
        self.digest = hashlib.sha256()
        self.byte_count = 0

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: bytearray) -> int:
        count = self.source.readinto(buffer)
        if count:
            self.digest.update(memoryview(buffer)[:count])
            self.byte_count += count
        return count


def _file_identity(stat: os.stat_result) -> tuple[int, int, int, int]:
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


@contextmanager
def verified_source(path: Path, contract: ArtifactContract) -> Iterator[TextIO]:
    """Check before parsing, then check the consumed bytes and unchanged source.

    The caller must consume to EOF. No success may be published inside this
    context: its exit performs the second integrity check.
    """

    if path.name != contract.filename:
        raise IntegrityError(f"source filename mismatch: expected {contract.filename}")
    with path.open("rb") as raw:
        before = _file_identity(os.fstat(raw.fileno()))
        if before[2] != contract.byte_size:
            raise IntegrityError(f"source size mismatch: {before[2]} != {contract.byte_size}")
        digest = hashlib.sha256()
        for chunk in iter(lambda: raw.read(1024 * 1024), b""):
            digest.update(chunk)
        if digest.hexdigest() != contract.sha256:
            raise IntegrityError("source SHA-256 mismatch before processing")
        raw.seek(0)
        hashing_reader = HashingReader(raw)
        with io.TextIOWrapper(io.BufferedReader(hashing_reader), encoding="utf-8",
                              errors="strict", newline="") as text:
            yield text
            if (hashing_reader.byte_count != contract.byte_size
                    or hashing_reader.digest.hexdigest() != contract.sha256):
                raise IntegrityError("source bytes consumed during processing do not match")
            # Detect replacement and in-place edits, even beyond decoder read-ahead.
            if (before != _file_identity(os.fstat(raw.fileno()))
                    or before != _file_identity(path.stat())):
                raise IntegrityError("source changed during processing")


@dataclass
class Reconciliation:
    row_count: int = 0
    labels: Counter[int] = field(default_factory=Counter)
    types: Counter[str] = field(default_factory=Counter)
    step_min: int | None = None
    step_max: int | None = None
    previous_step: int | None = None
    out_of_order_transitions: int = 0

    def observe(self, row: CanonicalTransaction) -> None:
        if row.source_row_number != self.row_count + 2:
            raise IntegrityError("source row numbers must be contiguous from 2")
        self.row_count += 1
        self.labels[row.is_fraud] += 1
        self.types[row.transaction_type] += 1
        self.step_min = row.step if self.step_min is None else min(self.step_min, row.step)
        self.step_max = row.step if self.step_max is None else max(self.step_max, row.step)
        if self.previous_step is not None and row.step < self.previous_step:
            self.out_of_order_transitions += 1
        self.previous_step = row.step

    def as_dict(self) -> dict[str, object]:
        return {
            "canonical_row_count": self.row_count,
            "legitimate_count": self.labels[0],
            "fraud_count": self.labels[1],
            "transaction_type_counts": dict(sorted(self.types.items())),
            "step_min": self.step_min,
            "step_max": self.step_max,
            "out_of_order_transitions": self.out_of_order_transitions,
        }

    def verify(self, contract: ArtifactContract) -> None:
        expected = {
            "canonical_row_count": contract.row_count,
            "legitimate_count": contract.legitimate_count,
            "fraud_count": contract.fraud_count,
            "transaction_type_counts": dict(contract.transaction_type_counts),
            "step_min": contract.step_min,
            "step_max": contract.step_max,
            "out_of_order_transitions": 0,
        }
        if self.as_dict() != expected:
            raise IntegrityError(
                f"canonical reconciliation failed: expected {expected}; observed {self.as_dict()}"
            )
