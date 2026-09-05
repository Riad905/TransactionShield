import csv
from pathlib import Path
from uuid import uuid4

import pytest

from transactionshield.ingestion import (
    MOMTSIM_PAPER_DATASET_V1_COLUMNS,
    CsvSchemaError,
    inspect_csv,
    iter_csv_rows,
)


@pytest.fixture
def csv_path():
    """Provide an isolated CSV path without relying on the host temp directory."""

    path = Path(__file__).parent / f".transactionshield-test-{uuid4().hex}.csv"
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def write_csv(path, header, rows=()):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def test_inspect_csv_accepts_contract_and_reports_extra_columns(csv_path):
    write_csv(csv_path, (*MOMTSIM_PAPER_DATASET_V1_COLUMNS, "sourceBatch"))

    report = inspect_csv(csv_path)

    assert report.path == csv_path
    assert report.columns == (*MOMTSIM_PAPER_DATASET_V1_COLUMNS, "sourceBatch")
    assert report.extra_columns == ("sourceBatch",)


def test_iter_csv_rows_is_lazy_and_preserves_string_values(csv_path):
    values = ("1", "transfer", "25.50", "C1", "100", "74.50", "C2", "5", "30.50", "0")
    write_csv(csv_path, MOMTSIM_PAPER_DATASET_V1_COLUMNS, (values,))

    rows = iter_csv_rows(csv_path)

    assert next(rows) == dict(
        zip(MOMTSIM_PAPER_DATASET_V1_COLUMNS, values, strict=True)
    )
    with pytest.raises(StopIteration):
        next(rows)


def test_inspect_csv_rejects_missing_required_columns(csv_path):
    write_csv(csv_path, MOMTSIM_PAPER_DATASET_V1_COLUMNS[:-1])

    with pytest.raises(CsvSchemaError, match=r"missing required columns: isFraud"):
        inspect_csv(csv_path)


def test_inspect_csv_rejects_duplicate_columns(csv_path):
    write_csv(csv_path, (*MOMTSIM_PAPER_DATASET_V1_COLUMNS, "amount"))

    with pytest.raises(CsvSchemaError, match=r"duplicate columns: amount"):
        inspect_csv(csv_path)


def test_iter_csv_rows_rejects_a_malformed_row(csv_path):
    write_csv(csv_path, MOMTSIM_PAPER_DATASET_V1_COLUMNS, (("1", "transfer"),))

    with pytest.raises(CsvSchemaError, match=r"row 2 has 2 fields; expected 10"):
        next(iter_csv_rows(csv_path))


def test_inspect_csv_rejects_an_empty_file(csv_path):
    csv_path.touch()

    with pytest.raises(CsvSchemaError, match=r"CSV file is empty"):
        inspect_csv(csv_path)
