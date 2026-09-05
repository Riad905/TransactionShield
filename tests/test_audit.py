import csv
import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

from transactionshield.audit import audit_csv, sha256_file
from transactionshield.ingestion import MOMTSIM_PAPER_DATASET_V1_COLUMNS


@pytest.fixture
def audit_paths():
    token = uuid4().hex
    csv_path = Path(__file__).parent / f".transactionshield-audit-{token}.csv"
    work_directory = Path(__file__).parent
    try:
        yield csv_path, work_directory
    finally:
        csv_path.unlink(missing_ok=True)
        for temporary in work_directory.glob(f".row-fingerprints-{token}*.sqlite"):
            temporary.unlink(missing_ok=True)


def write_rows(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(MOMTSIM_PAPER_DATASET_V1_COLUMNS)
        writer.writerows(rows)


def test_sha256_file_streams_expected_digest(audit_paths):
    csv_path, _ = audit_paths
    csv_path.write_bytes(b"transactionshield\n")

    assert sha256_file(csv_path) == hashlib.sha256(b"transactionshield\n").hexdigest()


def test_audit_csv_reproduces_core_quality_statistics(audit_paths):
    csv_path, work_directory = audit_paths
    rows = [
        ("0", "TRANSFER", "10.00", "A", "20", "10", "B", "5", "15", "1"),
        ("1", "PAYMENT", "5.00", "A", "10", "5", "C", "0", "5", "0"),
        ("1", "PAYMENT", "5.00", "A", "10", "5", "C", "0", "5", "0"),
        ("0", "TRANSFER", "0", "D", "0", "0", "B", "15", "15", "0"),
    ]
    write_rows(csv_path, rows)

    result = audit_csv(csv_path, work_directory=work_directory)

    assert result["artifact"]["column_count"] == 10
    assert result["rows"] == {
        "data_row_count": 4,
        "valid_row_count": 4,
        "malformed_row_count": 0,
        "duplicate_row_count": 1,
        "duplicate_method": "SHA-256 fingerprints of canonical parsed rows in a temporary on-disk index",
    }
    assert result["labels"]["counts"] == {"0": 3, "1": 1}
    assert result["labels"]["fraud_percentage"] == 25.0
    assert result["transaction_types"] == {"PAYMENT": 2, "TRANSFER": 2}
    assert result["label_counts_by_transaction_type"] == {
        "PAYMENT": {"0": 2},
        "TRANSFER": {"0": 1, "1": 1},
    }
    assert result["quality"]["non_positive_amount_count"] == 1
    assert result["temporal"]["out_of_order_transitions"] == 1
    assert result["entities"]["initiator_cardinality"] == 2
    assert result["entities"]["initiators_seen_at_multiple_steps"] == 1
    assert result["entities"]["initiator_label_profile"] == {
        "only_legitimate": 1,
        "only_fraud": 0,
        "mixed_legitimate_and_fraud": 1,
        "with_unexpected_labels": 0,
    }
    assert not result["paper_dataset_v1_comparison"]["calculated_values_match"]


def test_audit_csv_counts_wrong_width_as_malformed(audit_paths):
    csv_path, work_directory = audit_paths
    write_rows(csv_path, [("0", "TRANSFER")])

    result = audit_csv(csv_path, work_directory=work_directory)

    assert result["rows"]["data_row_count"] == 1
    assert result["rows"]["valid_row_count"] == 0
    assert result["rows"]["malformed_row_count"] == 1


def test_audit_csv_summarises_candidate_whole_step_windows(audit_paths):
    csv_path, work_directory = audit_paths
    rows = [
        (
            str(step),
            "TRANSFER",
            "1",
            "A",
            "5",
            "4",
            "B",
            "0",
            "1",
            str(step % 2),
        )
        for step in range(5)
    ]
    write_rows(csv_path, rows)

    result = audit_csv(csv_path, work_directory=work_directory)
    windows = result["temporal"]["candidate_whole_step_windows_60_20_20"]

    assert [
        (window["name"], window["step_min"], window["step_max"])
        for window in windows
    ] == [("train", 0, 2), ("validation", 3, 3), ("test", 4, 4)]
