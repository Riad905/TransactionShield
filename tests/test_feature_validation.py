from contextlib import contextmanager
from dataclasses import replace
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from transactionshield import feature_validation as validation
from transactionshield.canonical import parse_canonical_row
from transactionshield.validation import APPROVED_ARTIFACT, IntegrityError


def row(step, number, kind="TRANSFER", amount="1.20"):
    return parse_canonical_row(
        [str(step), kind, amount, "A", "-10", "-11", "B", "0", "1", "0"],
        number, APPROVED_ARTIFACT.sha256,
    )


def test_summary_counts_schema_cold_start_and_determinism():
    rows = [row(0, 2), row(0, 3, "PAYMENT"), row(96, 4), row(120, 5)]
    report = validation.validate_feature_rows(rows)
    with localcontext() as context:
        context.prec = 1
        repeated = validation.validate_feature_rows(iter(rows))
    assert repeated == report
    assert report["source_rows_consumed"] == 4
    assert report["eligible_examples_emitted"] == 3
    assert report["partition_counts"] == {"train": 1, "validation": 1, "test": 1}
    assert len(report["core_schema"]) == 9
    assert len(report["enhanced_additional_schema"]) == 2
    assert report["null_counts"]["initiator_prior_outgoing_amount_mean"] == 1
    assert report["null_counts"]["initiator_prior_outgoing_amount_max"] == 1
    assert report["zero_counts"]["initiator_prior_outgoing_count"] == 1
    assert report["zero_counts"]["recipient_prior_incoming_count"] == 1
    assert report["state"]["committed_rows"] == 4
    assert report["state"]["pending_rows"] == 0
    assert "labels" not in report


def test_report_ignores_labels_and_post_balances():
    rows = [row(0, 2), row(1, 3)]
    changed = [replace(current, is_fraud=1, initiator_balance_after=Decimal("987654321"),
                       recipient_balance_after=Decimal("-1")) for current in rows]
    assert validation.validate_feature_rows(rows) == validation.validate_feature_rows(changed)


def test_diagnostic_hash_separates_tiers():
    rows = [row(0, 2), row(1, 3)]
    changed = [replace(current, initiator_balance_before=Decimal("123")) for current in rows]
    baseline = validation.validate_feature_rows(rows)
    actual = validation.validate_feature_rows(changed)
    assert actual["core_diagnostic_sha256"] == baseline["core_diagnostic_sha256"]
    assert actual["enhanced_diagnostic_sha256"] != baseline["enhanced_diagnostic_sha256"]


def test_diagnostic_equality_ignores_decimal_spelling_not_numeric_value():
    assert validation._numeric_token(Decimal("1.20")) == validation._numeric_token(Decimal("1.200"))
    assert validation._numeric_token(Decimal("-0.0")) == validation._numeric_token(Decimal(0))
    assert validation._numeric_token(Decimal("1.20")) != validation._numeric_token(Decimal("1.21"))


def test_regression_cannot_return_success_report():
    with pytest.raises(ValueError, match="chronological regression"):
        validation.validate_feature_rows([row(1, 2), row(0, 3)])


def test_incomplete_upstream_cannot_return_success_report():
    def broken():
        yield row(0, 2)
        raise ValueError("invalid source")
    with pytest.raises(ValueError, match="invalid source"):
        validation.validate_feature_rows(broken())


def test_artifact_acceptance_checks_frozen_counts_and_gate_exit(monkeypatch):
    @contextmanager
    def source(*args):
        yield None
    monkeypatch.setattr(validation, "verified_source", source)
    monkeypatch.setattr(validation, "iter_canonical_records", lambda *args: iter([row(0, 2)]))
    with pytest.raises(IntegrityError, match="population/splits"):
        validation.validate_artifact(Path(__file__))

    @contextmanager
    def mutated_source(*args):
        yield None
        raise IntegrityError("source changed after reading")
    monkeypatch.setattr(validation, "verified_source", mutated_source)
    with pytest.raises(IntegrityError, match="source changed"):
        validation.validate_artifact(Path(__file__))


def test_cli_no_output_outside_ignored_report_area():
    with pytest.raises(SystemExit) as error:
        validation.main([str(Path(__file__)), "--report-output", str(Path(__file__).parent / "report.json")])
    assert error.value.code == 2
