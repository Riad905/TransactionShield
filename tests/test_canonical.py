import csv
import io
from decimal import Decimal, localcontext

import pytest

from transactionshield.canonical import (
    CANONICAL_COLUMNS, CanonicalValidationError, iter_canonical_records, parse_canonical_row,
)
from transactionshield.contracts import deterministic_transaction_id
from transactionshield.ingestion import MOMTSIM_PAPER_DATASET_V1_COLUMNS
from transactionshield.validation import APPROVED_ARTIFACT


def source_row(**changes):
    row = dict(zip(MOMTSIM_PAPER_DATASET_V1_COLUMNS, (
        "0", "TRANSFER", "+0001.200", " 0000123 ", "-0002.00", "-0.00",
        "B56-0001572", "123456789012345678901234567890.123456", "0.0", "1",
    ), strict=True))
    row.update(changes)
    return [row[column] for column in MOMTSIM_PAPER_DATASET_V1_COLUMNS]


def csv_text(header, rows=()):
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    output.seek(0)
    return output


def test_exact_header_typed_values_and_lossless_rendering():
    values = source_row()
    with localcontext() as context:
        context.prec = 2  # Parsing/serialising must not round to ambient precision.
        record = list(iter_canonical_records(
            csv_text(MOMTSIM_PAPER_DATASET_V1_COLUMNS, [values]), APPROVED_ARTIFACT.sha256,
        ))[0]
        assert record.amount == Decimal("1.200")
        assert record.initiator_balance_before == Decimal("-2.00")
        assert record.initiator_balance_after.as_tuple().sign == 1
        assert record.csv_values()[3:] == tuple([0, *values[1:-1], 1])
    assert record.initiator_id == " 0000123 "
    assert record.recipient_id == "B56-0001572"
    assert str(record.transaction_id) == "9a10d98b-85ee-5bbb-bbc5-ed4148483b9b"
    assert str(record.artifact_id) == "3de76748-4701-53f9-8ddf-ccaf6615d63a"
    assert tuple(CANONICAL_COLUMNS) == (
        "transaction_id", "artifact_id", "source_row_number", "step", "transaction_type",
        "amount", "initiator_id", "initiator_balance_before", "initiator_balance_after",
        "recipient_id", "recipient_balance_before", "recipient_balance_after", "is_fraud",
    )


@pytest.mark.parametrize("header", [
    (), MOMTSIM_PAPER_DATASET_V1_COLUMNS[:-1],
    (*MOMTSIM_PAPER_DATASET_V1_COLUMNS, "extra"),
    tuple(reversed(MOMTSIM_PAPER_DATASET_V1_COLUMNS)),
    ("step", *MOMTSIM_PAPER_DATASET_V1_COLUMNS[:-1]),
    (" step", *MOMTSIM_PAPER_DATASET_V1_COLUMNS[1:]),
    ("Step", *MOMTSIM_PAPER_DATASET_V1_COLUMNS[1:]),
])
def test_non_exact_headers_rejected(header):
    with pytest.raises(CanonicalValidationError, match="row 1, header"):
        list(iter_canonical_records(csv_text(header, [source_row()]), APPROVED_ARTIFACT.sha256))


def test_empty_file_rejected():
    with pytest.raises(CanonicalValidationError, match="header"):
        list(iter_canonical_records(io.StringIO(""), APPROVED_ARTIFACT.sha256))


@pytest.mark.parametrize("values", [source_row()[:-1], [*source_row(), "extra"]])
def test_width_rejected(values):
    with pytest.raises(CanonicalValidationError, match="row 2, record"):
        parse_canonical_row(values, 2, APPROVED_ARTIFACT.sha256)


@pytest.mark.parametrize(("column", "value"), [
    ("step", "-1"), ("step", "1.5"), ("step", "NaN"), ("step", ""),
    ("step", " 1"), ("step", str(2**31)),
    ("transactionType", "transfer"), ("transactionType", "UNKNOWN"),
    ("isFraud", "2"), ("isFraud", "1.0"), ("isFraud", " 0"),
    ("initiator", ""), ("recipient", ""),
    ("initiator", " \t\n"), ("recipient", "\u2003"),
    ("amount", "0"), ("amount", "-0.00"), ("amount", "-1.20"),
    ("amount", "oops"), ("amount", "1e2"), ("amount", " 1.2"),
    ("amount", "1_000"), ("amount", "NaN"), ("amount", "Infinity"),
    ("oldBalInitiator", "-Infinity"), ("newBalInitiator", "NaN"),
    ("oldBalRecipient", "sNaN"), ("newBalRecipient", ""),
])
def test_semantic_rejections_have_context(column, value):
    with pytest.raises(CanonicalValidationError, match=f"row 2, {column}"):
        parse_canonical_row(source_row(**{column: value}), 2, APPROVED_ARTIFACT.sha256)


@pytest.mark.parametrize("identifier", ["0000", "83-0004000-2394", "user,quoted", 'a"b',
                                         "  valid  ", "a\nb", "é", "x" * 1000])
def test_identifiers_have_no_sample_specific_constraints(identifier):
    record = parse_canonical_row(source_row(initiator=identifier, recipient=identifier),
                                 2, APPROVED_ARTIFACT.sha256)
    assert record.initiator_id == record.recipient_id == identifier


@pytest.mark.parametrize("transaction_type", ["DEBIT", "DEPOSIT", "PAYMENT", "WITHDRAWAL"])
def test_non_transfers_preserved(transaction_type):
    record = parse_canonical_row(source_row(transactionType=transaction_type, isFraud="0"),
                                 2, APPROVED_ARTIFACT.sha256)
    assert record.transaction_type == transaction_type


@pytest.mark.parametrize("row_number", [True, False, 2.0, "2", None, 0, 1, -2, 2**63])
def test_public_identity_and_parser_reject_invalid_row_number_types(row_number):
    for function in (lambda: deterministic_transaction_id(APPROVED_ARTIFACT.sha256, row_number),
                     lambda: parse_canonical_row(source_row(), row_number, APPROVED_ARTIFACT.sha256)):
        with pytest.raises(ValueError, match="source_row_number"):
            function()


def test_identity_repeatability_and_artifact_separation():
    original = deterministic_transaction_id(APPROVED_ARTIFACT.sha256, 2)
    assert original == deterministic_transaction_id(APPROVED_ARTIFACT.sha256, 2)
    assert original != deterministic_transaction_id(APPROVED_ARTIFACT.sha256, 3)
    assert original != deterministic_transaction_id("a" * 64, 2)


def test_logical_row_lineage_with_embedded_newline():
    stream = csv_text(MOMTSIM_PAPER_DATASET_V1_COLUMNS,
                      [source_row(initiator="line1\nline2"), source_row()])
    assert [r.source_row_number for r in iter_canonical_records(stream, APPROVED_ARTIFACT.sha256)] == [2, 3]


def test_malformed_quoting_has_row_context():
    stream = io.StringIO(",".join(MOMTSIM_PAPER_DATASET_V1_COLUMNS) + '\n"unterminated')
    with pytest.raises(CanonicalValidationError, match="row 2, record"):
        list(iter_canonical_records(stream, APPROVED_ARTIFACT.sha256))


@pytest.mark.parametrize(("literal", "expected"), [("+1", 1), ("0001", 1), ("-0", 0),
                                                    (str(2**31 - 1), 2**31 - 1)])
def test_nonnegative_integer_semantics_not_sample_step_maximum(literal, expected):
    assert parse_canonical_row(source_row(step=literal), 2, APPROVED_ARTIFACT.sha256).step == expected


def test_bom_is_not_silently_stripped_from_production_header():
    stream = io.StringIO("\ufeff" + csv_text(MOMTSIM_PAPER_DATASET_V1_COLUMNS, [source_row()]).getvalue())
    with pytest.raises(CanonicalValidationError, match="header"):
        list(iter_canonical_records(stream, APPROVED_ARTIFACT.sha256))
