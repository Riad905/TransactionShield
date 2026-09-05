"""Stage 3 data and scoring-contract inspection utilities."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from transactionshield.ingestion import iter_csv_rows

PRIMARY_MODEL_TRANSACTION_TYPE = "TRANSFER"
TRANSACTION_ID_NAMESPACE = UUID("e42d9db1-0152-5973-b3b0-6df189dc50e4")
NUMERIC_CONTRACT_COLUMNS = (
    "amount",
    "oldBalInitiator",
    "newBalInitiator",
    "oldBalRecipient",
    "newBalRecipient",
)
IDENTIFIER_CONTRACT_COLUMNS = ("initiator", "recipient")

_PLAIN_DECIMAL = re.compile(
    r"^(?P<sign>[+-]?)(?P<integer>[0-9]+)(?:\.(?P<fraction>[0-9]+))?$"
)
_NUMERIC_IDENTIFIER = re.compile(r"^[0-9]+$")
_PREFIXED_IDENTIFIER = re.compile(r"^[0-9]{2}-[0-9]{7}$")
_EXTENDED_PREFIXED_IDENTIFIER = re.compile(r"^[0-9]{2}-[0-9]{7}-[0-9]{4}$")
_LETTER_PREFIXED_IDENTIFIER = re.compile(r"^[A-Z][0-9]{2}-[0-9]{7}$")
_OTHER_HYPHENATED_NUMERIC_IDENTIFIER = re.compile(r"^[0-9]+-[0-9]+$")


@dataclass(frozen=True, slots=True)
class TransferStepSummary:
    """Counts for the primary predictive population in one complete step."""

    step: int
    eligible_transfer_count: int
    fraudulent_transfer_count: int
    legitimate_transfer_count: int

    @property
    def fraud_rate_percent(self) -> Decimal:
        if not self.eligible_transfer_count:
            return Decimal(0)
        return (
            Decimal(self.fraudulent_transfer_count)
            * Decimal(100)
            / Decimal(self.eligible_transfer_count)
        )


def is_primary_model_eligible(transaction_type: str) -> bool:
    """Return whether a source transaction belongs to the primary population."""

    return transaction_type == PRIMARY_MODEL_TRANSACTION_TYPE


def iter_primary_model_rows(
    rows: Iterable[Mapping[str, str]],
) -> Iterator[Mapping[str, str]]:
    """Yield only exact-match TRANSFER rows without materialising the input."""

    for row in rows:
        if is_primary_model_eligible(row["transactionType"]):
            yield row


def is_strictly_prior_step(history_step: int, current_step: int) -> bool:
    """Return whether history is available under the locked point-in-time rule."""

    return history_step < current_step


def deterministic_transaction_id(
    artifact_sha256: str, source_row_number: int
) -> UUID:
    """Derive stable row identity from immutable artifact identity and row lineage."""

    if re.fullmatch(r"[0-9a-f]{64}", artifact_sha256) is None:
        raise ValueError("artifact_sha256 must be 64 lowercase hexadecimal characters")
    if source_row_number < 2:
        raise ValueError("source_row_number must count the header as row 1")
    return uuid5(
        TRANSACTION_ID_NAMESPACE,
        f"{artifact_sha256}:{source_row_number}",
    )


def _step_summaries(
    step_label_counts: Mapping[int, Counter[str]],
) -> tuple[TransferStepSummary, ...]:
    summaries: list[TransferStepSummary] = []
    for step in sorted(step_label_counts):
        counts = step_label_counts[step]
        fraudulent = counts.get("1", 0)
        legitimate = counts.get("0", 0)
        summaries.append(
            TransferStepSummary(
                step=step,
                eligible_transfer_count=fraudulent + legitimate,
                fraudulent_transfer_count=fraudulent,
                legitimate_transfer_count=legitimate,
            )
        )
    return tuple(summaries)


def summarise_transfer_steps(
    rows: Iterable[Mapping[str, str]],
) -> tuple[TransferStepSummary, ...]:
    """Return deterministic step-sorted counts for exact-match TRANSFER rows."""

    step_label_counts: dict[int, Counter[str]] = {}
    for row in iter_primary_model_rows(rows):
        step = int(row["step"])
        label = row["isFraud"]
        if label not in {"0", "1"}:
            raise ValueError(f"Unexpected fraud label {label!r} at step {step}")
        step_label_counts.setdefault(step, Counter())[label] += 1
    return _step_summaries(step_label_counts)


def _new_numeric_state() -> dict[str, Any]:
    return {
        "minimum": None,
        "maximum": None,
        "maximum_integer_digits": 0,
        "maximum_decimal_places": 0,
    }


def _update_numeric_state(state: dict[str, Any], raw_value: str) -> None:
    match = _PLAIN_DECIMAL.fullmatch(raw_value)
    if match is None:
        raise ValueError(f"Value is not a plain decimal literal: {raw_value!r}")

    try:
        number = Decimal(raw_value)
    except InvalidOperation as error:
        raise ValueError(f"Invalid decimal value: {raw_value!r}") from error

    integer_part = match.group("integer").lstrip("0") or "0"
    fraction_part = match.group("fraction") or ""
    state["maximum_integer_digits"] = max(
        state["maximum_integer_digits"], len(integer_part)
    )
    state["maximum_decimal_places"] = max(
        state["maximum_decimal_places"], len(fraction_part)
    )
    minimum = state["minimum"]
    maximum = state["maximum"]
    state["minimum"] = number if minimum is None else min(minimum, number)
    state["maximum"] = number if maximum is None else max(maximum, number)


def _identifier_format(value: str) -> str:
    if _NUMERIC_IDENTIFIER.fullmatch(value):
        return "numeric"
    if _PREFIXED_IDENTIFIER.fullmatch(value):
        return "two_digit_prefix_hyphen_seven_digits"
    if _EXTENDED_PREFIXED_IDENTIFIER.fullmatch(value):
        return "two_digit_prefix_hyphen_seven_digits_hyphen_four_digits"
    if _LETTER_PREFIXED_IDENTIFIER.fullmatch(value):
        return "letter_two_digits_hyphen_seven_digits"
    if _OTHER_HYPHENATED_NUMERIC_IDENTIFIER.fullmatch(value):
        return "other_hyphenated_numeric"
    return "other"


def _new_identifier_state() -> dict[str, Any]:
    return {
        "minimum_length": None,
        "maximum_length": 0,
        "length_counts": Counter(),
        "format_counts": Counter(),
        "examples_by_format": {},
    }


def _update_identifier_state(state: dict[str, Any], value: str) -> None:
    value_length = len(value)
    minimum_length = state["minimum_length"]
    state["minimum_length"] = (
        value_length if minimum_length is None else min(minimum_length, value_length)
    )
    state["maximum_length"] = max(state["maximum_length"], value_length)
    state["length_counts"][value_length] += 1
    identifier_format = _identifier_format(value)
    state["format_counts"][identifier_format] += 1
    examples = state["examples_by_format"].setdefault(identifier_format, [])
    if value not in examples and len(examples) < 3:
        examples.append(value)


def inspect_contract_rows(rows: Iterable[Mapping[str, str]]) -> dict[str, Any]:
    """Inspect representation and population contracts in a single streaming pass."""

    numeric_states = {
        column: _new_numeric_state() for column in NUMERIC_CONTRACT_COLUMNS
    }
    identifier_states = {
        column: _new_identifier_state() for column in IDENTIFIER_CONTRACT_COLUMNS
    }
    step_label_counts: dict[int, Counter[str]] = {}
    row_count = 0

    for row_number, row in enumerate(rows, start=2):
        row_count += 1
        for column, state in numeric_states.items():
            try:
                _update_numeric_state(state, row[column])
            except ValueError as error:
                raise ValueError(f"{column} at CSV row {row_number}: {error}") from error
        for column, state in identifier_states.items():
            _update_identifier_state(state, row[column])

        transaction_type = row["transactionType"]
        if is_primary_model_eligible(transaction_type):
            try:
                step = int(row["step"])
            except ValueError as error:
                raise ValueError(
                    f"step at CSV row {row_number} is not an integer"
                ) from error
            label = row["isFraud"]
            if label not in {"0", "1"}:
                raise ValueError(
                    f"Unexpected fraud label {label!r} at CSV row {row_number}"
                )
            step_label_counts.setdefault(step, Counter())[label] += 1

    if row_count == 0:
        raise ValueError("Contract inspection requires at least one data row")

    numeric_result = {}
    for column, state in numeric_states.items():
        numeric_result[column] = {
            "minimum": format(state["minimum"], "f"),
            "maximum": format(state["maximum"], "f"),
            "maximum_integer_digits": state["maximum_integer_digits"],
            "maximum_decimal_places": state["maximum_decimal_places"],
        }

    identifier_result = {}
    for column, state in identifier_states.items():
        identifier_result[column] = {
            "minimum_length": state["minimum_length"],
            "maximum_length": state["maximum_length"],
            "length_counts": {
                str(length): count
                for length, count in sorted(state["length_counts"].items())
            },
            "format_counts": dict(sorted(state["format_counts"].items())),
            "examples_by_format": dict(sorted(state["examples_by_format"].items())),
        }

    summaries = _step_summaries(step_label_counts)
    eligible_count = sum(item.eligible_transfer_count for item in summaries)
    fraudulent_count = sum(item.fraudulent_transfer_count for item in summaries)
    legitimate_count = sum(item.legitimate_transfer_count for item in summaries)
    fraud_rate = (
        Decimal(fraudulent_count) * Decimal(100) / Decimal(eligible_count)
        if eligible_count
        else Decimal(0)
    )

    return {
        "source_row_count": row_count,
        "numeric_characteristics": numeric_result,
        "identifier_characteristics": identifier_result,
        "primary_population": {
            "eligibility_rule": 'transactionType == "TRANSFER"',
            "eligible_transfer_count": eligible_count,
            "fraudulent_transfer_count": fraudulent_count,
            "legitimate_transfer_count": legitimate_count,
            "fraud_rate_percent": str(fraud_rate),
        },
        "transfer_step_summaries": [
            {
                **asdict(summary),
                "fraud_rate_percent": str(summary.fraud_rate_percent),
            }
            for summary in summaries
        ],
    }


def inspect_contract_csv(path: str | Path) -> dict[str, Any]:
    """Inspect the canonical CSV without loading it into memory."""

    return inspect_contract_rows(iter_csv_rows(path))


def write_contract_report(report: Mapping[str, Any], path: str | Path) -> None:
    """Write a stable JSON representation of a contract inspection report."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def write_transfer_step_summary(
    summaries: Iterable[Mapping[str, Any]], path: str | Path
) -> None:
    """Write the compact, deterministic per-step transfer report as CSV."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = (
        "step",
        "eligible_transfer_count",
        "fraudulent_transfer_count",
        "legitimate_transfer_count",
        "fraud_rate_percent",
    )
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for summary in summaries:
            writer.writerow({column: summary[column] for column in fieldnames})


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--report-output", type=Path)
    parser.add_argument("--step-output", type=Path)
    args = parser.parse_args(argv)

    report = inspect_contract_csv(args.csv_path)
    if args.report_output:
        write_contract_report(report, args.report_output)
        print(f"wrote contract report to {args.report_output}")
    if args.step_output:
        write_transfer_step_summary(report["transfer_step_summaries"], args.step_output)
        print(f"wrote transfer step summary to {args.step_output}")
    if not args.report_output and not args.step_output:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
