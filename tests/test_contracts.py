import csv
from pathlib import Path
from uuid import uuid4

import pytest

from transactionshield.contracts import (
    deterministic_transaction_id,
    inspect_contract_csv,
    is_primary_model_eligible,
    is_strictly_prior_step,
    iter_primary_model_rows,
    summarise_transfer_steps,
)
from transactionshield.ingestion import MOMTSIM_PAPER_DATASET_V1_COLUMNS


@pytest.fixture
def contract_csv_path():
    path = Path(__file__).parent / f".transactionshield-contract-{uuid4().hex}.csv"
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def _row(step, transaction_type, amount, initiator, recipient, label):
    return {
        "step": str(step),
        "transactionType": transaction_type,
        "amount": amount,
        "initiator": initiator,
        "oldBalInitiator": "10000000.00",
        "newBalInitiator": "-1.25",
        "recipient": recipient,
        "oldBalRecipient": "0.0",
        "newBalRecipient": "999.99",
        "isFraud": str(label),
    }


def _write_rows(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MOMTSIM_PAPER_DATASET_V1_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def test_primary_population_requires_exact_transfer_type():
    rows = [
        _row(0, "TRANSFER", "1.00", "123", "45-0000001", 1),
        _row(0, "PAYMENT", "2.00", "456", "789", 0),
        _row(0, "transfer", "3.00", "789", "012", 0),
    ]

    assert is_primary_model_eligible("TRANSFER")
    assert not is_primary_model_eligible("PAYMENT")
    assert not is_primary_model_eligible("transfer")
    assert list(iter_primary_model_rows(rows)) == [rows[0]]


def test_history_requires_a_strictly_earlier_step():
    assert is_strictly_prior_step(4, 5)
    assert not is_strictly_prior_step(5, 5)
    assert not is_strictly_prior_step(6, 5)


def test_transaction_identity_is_deterministic_and_lineage_specific():
    artifact_sha256 = (
        "da951eb95735da96271740a3e66b676b342d3831ce3111cd19dbfa020d3bd0a7"
    )

    first = deterministic_transaction_id(artifact_sha256, 2)

    assert str(first) == "9a10d98b-85ee-5bbb-bbc5-ed4148483b9b"
    assert deterministic_transaction_id(artifact_sha256, 2) == first
    assert deterministic_transaction_id(artifact_sha256, 3) != first


def test_transfer_step_summaries_are_sorted_and_deterministic():
    rows = [
        _row(2, "TRANSFER", "1.00", "123", "456", 1),
        _row(1, "PAYMENT", "1.00", "123", "456", 0),
        _row(1, "TRANSFER", "1.00", "123", "456", 0),
        _row(2, "TRANSFER", "1.00", "123", "456", 0),
    ]

    forward = summarise_transfer_steps(rows)
    reverse = summarise_transfer_steps(reversed(rows))

    assert forward == reverse
    assert [summary.step for summary in forward] == [1, 2]
    assert forward[0].eligible_transfer_count == 1
    assert forward[0].fraudulent_transfer_count == 0
    assert forward[1].eligible_transfer_count == 2
    assert forward[1].fraudulent_transfer_count == 1


def test_contract_inspection_reports_exact_representation(contract_csv_path):
    rows = [
        _row(0, "TRANSFER", "2142928.28", "1234567890123456", "25-0000401", 1),
        _row(1, "TRANSFER", "0.24", "9876543210987654", "1234567890123456", 0),
        _row(2, "PAYMENT", "1.00", "1111111111111111", "83-0004000-2394", 0),
        _row(3, "DEBIT", "1.00", "2222222222222222", "B56-0001572", 0),
    ]
    _write_rows(contract_csv_path, rows)

    report = inspect_contract_csv(contract_csv_path)

    assert report["numeric_characteristics"]["amount"] == {
        "minimum": "0.24",
        "maximum": "2142928.28",
        "maximum_integer_digits": 7,
        "maximum_decimal_places": 2,
    }
    assert report["identifier_characteristics"]["initiator"]["format_counts"] == {
        "numeric": 4
    }
    assert report["identifier_characteristics"]["recipient"]["format_counts"] == {
        "letter_two_digits_hyphen_seven_digits": 1,
        "numeric": 1,
        "two_digit_prefix_hyphen_seven_digits": 1,
        "two_digit_prefix_hyphen_seven_digits_hyphen_four_digits": 1,
    }
    assert report["primary_population"] == {
        "eligibility_rule": 'transactionType == "TRANSFER"',
        "eligible_transfer_count": 2,
        "fraudulent_transfer_count": 1,
        "legitimate_transfer_count": 1,
        "fraud_rate_percent": "50",
    }
