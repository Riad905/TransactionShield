"""Streaming integrity and quality audit for TransactionShield CSV artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sqlite3
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

from transactionshield.ingestion import MOMTSIM_PAPER_DATASET_V1_COLUMNS, inspect_csv

PAPER_DATASET_V1_EXPECTATIONS = {
    "data_rows": 1_720_181,
    "legitimate_rows": 1_544_663,
    "fraud_rows": 175_518,
}

FULL_DISTINCT_COLUMNS = {"step", "transactionType", "initiator", "recipient", "isFraud"}
NUMERIC_COLUMNS = {
    "step",
    "amount",
    "oldBalInitiator",
    "newBalInitiator",
    "oldBalRecipient",
    "newBalRecipient",
    "isFraud",
}
BALANCE_COLUMNS = (
    "oldBalInitiator",
    "newBalInitiator",
    "oldBalRecipient",
    "newBalRecipient",
)
DISTINCT_CAP = 10_000


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    """Return a lowercase SHA-256 digest without loading the file into memory."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


class _DuplicateTracker:
    """Track canonical row fingerprints in a temporary on-disk SQLite index."""

    def __init__(self, work_directory: Path) -> None:
        work_directory.mkdir(parents=True, exist_ok=True)
        self.path = work_directory / f".row-fingerprints-{uuid4().hex}.sqlite"
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA journal_mode = OFF")
        self.connection.execute("PRAGMA synchronous = OFF")
        self.connection.execute("PRAGMA locking_mode = EXCLUSIVE")
        self.connection.execute(
            "CREATE TABLE fingerprints (digest BLOB PRIMARY KEY) WITHOUT ROWID"
        )

    def add(self, values: Sequence[str]) -> bool:
        """Return True when this parsed row has already been observed."""

        canonical = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).digest()
        cursor = self.connection.execute(
            "INSERT OR IGNORE INTO fingerprints (digest) VALUES (?)", (fingerprint,)
        )
        return cursor.rowcount == 0

    def close(self) -> None:
        self.connection.close()
        self.path.unlink(missing_ok=True)


def _update_type_state(state: dict[str, bool], value: str) -> float | None:
    if state["integer"]:
        try:
            int(value)
        except ValueError:
            state["integer"] = False

    number: float | None
    try:
        number = float(value)
    except ValueError:
        state["number"] = False
        number = None
    return number


def _inferred_type(state: dict[str, bool]) -> str:
    if state["integer"]:
        return "integer"
    if state["number"]:
        return "number"
    return "string"


def _update_majority_vote(state: dict[str, Any], value: str) -> None:
    if state["balance"] == 0:
        state["candidate"] = value
        state["balance"] = 1
    elif value == state["candidate"]:
        state["balance"] += 1
    else:
        state["balance"] -= 1


def _update_entity(
    activity: dict[str, list[Any]], entity: str, step: int | None, label: str
) -> None:
    current = activity.get(entity)
    if current is None:
        activity[entity] = [1, step, step, False, 0, 0, 0]
        current = activity[entity]
    else:
        current[0] += 1
        if step is not None:
            if current[1] is None:
                current[1] = step
                current[2] = step
            else:
                current[1] = min(current[1], step)
                current[2] = max(current[2], step)
                if step != current[1] or step != current[2]:
                    current[3] = True

    if label == "0":
        current[4] += 1
    elif label == "1":
        current[5] += 1
    else:
        current[6] += 1


def _entity_label_profile(activity: dict[str, list[Any]]) -> dict[str, int]:
    return {
        "only_legitimate": sum(item[4] > 0 and item[5] == 0 for item in activity.values()),
        "only_fraud": sum(item[5] > 0 and item[4] == 0 for item in activity.values()),
        "mixed_legitimate_and_fraud": sum(
            item[4] > 0 and item[5] > 0 for item in activity.values()
        ),
        "with_unexpected_labels": sum(item[6] > 0 for item in activity.values()),
    }


def _delta_pattern(old: float, new: float, amount: float) -> str:
    tolerance = max(0.01, abs(amount) * 1e-9)
    delta = new - old
    if math.isclose(delta, amount, abs_tol=tolerance):
        return "increase_by_amount"
    if math.isclose(delta, -amount, abs_tol=tolerance):
        return "decrease_by_amount"
    if math.isclose(delta, 0.0, abs_tol=0.01):
        return "unchanged"
    return "other"


def _verify_majority_candidates(
    path: Path,
    encoding: str,
    columns: tuple[str, ...],
    candidates: dict[str, str | None],
) -> Counter[str]:
    counts: Counter[str] = Counter()
    with path.open("r", encoding=encoding, errors="strict", newline="") as handle:
        reader = csv.reader(handle, strict=True)
        next(reader)
        for values in reader:
            if len(values) != len(columns):
                continue
            for index, column in enumerate(columns):
                candidate = candidates[column]
                if candidate is not None and values[index].strip() == candidate:
                    counts[column] += 1
    return counts


def _candidate_temporal_windows(
    steps: set[int], label_counts_by_step: dict[int, Counter[str]]
) -> list[dict[str, Any]]:
    """Summarise a feasibility-only 60/20/20 split on whole step values."""

    ordered_steps = sorted(steps)
    if len(ordered_steps) < 3:
        return []

    train_boundary = max(1, int(len(ordered_steps) * 0.60))
    validation_boundary = max(train_boundary + 1, int(len(ordered_steps) * 0.80))
    validation_boundary = min(validation_boundary, len(ordered_steps) - 1)
    partitions = (
        ("train", ordered_steps[:train_boundary]),
        ("validation", ordered_steps[train_boundary:validation_boundary]),
        ("test", ordered_steps[validation_boundary:]),
    )
    summaries: list[dict[str, Any]] = []
    for name, window_steps in partitions:
        legitimate = sum(label_counts_by_step[step].get("0", 0) for step in window_steps)
        fraud = sum(label_counts_by_step[step].get("1", 0) for step in window_steps)
        rows = sum(sum(label_counts_by_step[step].values()) for step in window_steps)
        summaries.append(
            {
                "name": name,
                "step_min": window_steps[0],
                "step_max": window_steps[-1],
                "step_count": len(window_steps),
                "row_count": rows,
                "legitimate_count": legitimate,
                "fraud_count": fraud,
                "fraud_percentage": fraud / rows * 100 if rows else 0.0,
            }
        )
    return summaries


def audit_csv(
    path: str | Path,
    *,
    work_directory: str | Path,
    progress_every: int | None = None,
    progress: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    """Stream a MoMTSim CSV and return reproducible integrity/quality statistics."""

    csv_path = Path(path)
    schema = inspect_csv(csv_path, MOMTSIM_PAPER_DATASET_V1_COLUMNS)
    with csv_path.open("rb") as binary_handle:
        prefix = binary_handle.read(3)
    has_utf8_bom = prefix == b"\xef\xbb\xbf"
    encoding = "utf-8-sig" if has_utf8_bom else "utf-8"
    columns = schema.columns

    null_counts: Counter[str] = Counter()
    examples: dict[str, list[str]] = {column: [] for column in columns}
    type_states = {
        column: {"integer": True, "number": True} for column in columns
    }
    numeric_min: dict[str, float | None] = {column: None for column in columns}
    numeric_max: dict[str, float | None] = {column: None for column in columns}
    exact_distinct: dict[str, set[str]] = {
        column: set() for column in columns if column in FULL_DISTINCT_COLUMNS
    }
    capped_distinct: dict[str, set[str]] = {
        column: set() for column in columns if column not in FULL_DISTINCT_COLUMNS
    }
    distinct_overflow: set[str] = set()
    majority_votes: dict[str, dict[str, Any]] = {
        column: {"candidate": None, "balance": 0} for column in columns
    }

    label_counts: Counter[str] = Counter()
    transaction_type_counts: Counter[str] = Counter()
    label_counts_by_transaction_type: dict[str, Counter[str]] = {}
    label_counts_by_step: dict[int, Counter[str]] = {}
    initiator_activity: dict[str, list[Any]] = {}
    recipient_activity: dict[str, list[Any]] = {}
    step_values: set[int] = set()
    previous_step: int | None = None
    out_of_order_transitions = 0
    invalid_step_rows = 0
    invalid_numeric_counts: Counter[str] = Counter()
    non_finite_counts: Counter[str] = Counter()
    negative_balance_counts: Counter[str] = Counter()
    non_positive_amount_count = 0
    balance_patterns: dict[str, dict[str, Counter[str]]] = {}
    balance_pattern_labels: dict[str, dict[str, Counter[str]]] = {
        "initiator": {},
        "recipient": {},
        "combined": {},
    }
    negative_balance_labels: dict[str, Counter[str]] = {
        column: Counter() for column in BALANCE_COLUMNS
    }
    any_negative_balance_labels: Counter[str] = Counter()

    data_rows = 0
    valid_rows = 0
    malformed_rows = 0
    duplicate_rows = 0
    duplicate_tracker = _DuplicateTracker(Path(work_directory))

    try:
        with csv_path.open(
            "r", encoding=encoding, errors="strict", newline=""
        ) as handle:
            reader = csv.reader(handle, strict=True)
            next(reader)
            while True:
                try:
                    values = next(reader)
                except StopIteration:
                    break
                except csv.Error:
                    data_rows += 1
                    malformed_rows += 1
                    continue

                data_rows += 1
                if len(values) != len(columns):
                    malformed_rows += 1
                    continue

                valid_rows += 1
                duplicate_rows += int(duplicate_tracker.add(values))
                row = dict(zip(columns, values, strict=True))

                for column, raw_value in row.items():
                    value = raw_value.strip()
                    if not value:
                        null_counts[column] += 1
                        continue

                    if value not in examples[column] and len(examples[column]) < 3:
                        examples[column].append(value)
                    _update_majority_vote(majority_votes[column], value)

                    if column in exact_distinct:
                        exact_distinct[column].add(value)
                    elif column not in distinct_overflow:
                        capped_distinct[column].add(value)
                        if len(capped_distinct[column]) > DISTINCT_CAP:
                            capped_distinct[column].clear()
                            distinct_overflow.add(column)

                    number = _update_type_state(type_states[column], value)
                    if column in NUMERIC_COLUMNS:
                        if number is None:
                            invalid_numeric_counts[column] += 1
                        elif not math.isfinite(number):
                            non_finite_counts[column] += 1
                        else:
                            current_min = numeric_min[column]
                            current_max = numeric_max[column]
                            numeric_min[column] = (
                                number if current_min is None else min(current_min, number)
                            )
                            numeric_max[column] = (
                                number if current_max is None else max(current_max, number)
                            )

                transaction_type = row["transactionType"].strip()
                label = row["isFraud"].strip()
                transaction_type_counts[transaction_type] += 1
                label_counts[label] += 1
                label_counts_by_transaction_type.setdefault(
                    transaction_type, Counter()
                )[label] += 1

                try:
                    step = int(row["step"].strip())
                except ValueError:
                    invalid_step_rows += 1
                    step = None
                if step is not None:
                    step_values.add(step)
                    label_counts_by_step.setdefault(step, Counter())[label] += 1
                    if previous_step is not None and step < previous_step:
                        out_of_order_transitions += 1
                    previous_step = step
                _update_entity(
                    initiator_activity, row["initiator"].strip(), step, label
                )
                _update_entity(
                    recipient_activity, row["recipient"].strip(), step, label
                )

                parsed: dict[str, float] = {}
                for column in ("amount", *BALANCE_COLUMNS):
                    try:
                        value = float(row[column].strip())
                    except ValueError:
                        continue
                    if math.isfinite(value):
                        parsed[column] = value

                amount = parsed.get("amount")
                if amount is not None and amount <= 0:
                    non_positive_amount_count += 1
                row_has_negative_balance = False
                for column in BALANCE_COLUMNS:
                    balance = parsed.get(column)
                    if balance is not None and balance < 0:
                        negative_balance_counts[column] += 1
                        negative_balance_labels[column][label] += 1
                        row_has_negative_balance = True
                if row_has_negative_balance:
                    any_negative_balance_labels[label] += 1

                if amount is not None and all(
                    column in parsed for column in BALANCE_COLUMNS
                ):
                    patterns = balance_patterns.setdefault(
                        transaction_type,
                        {
                            "initiator": Counter(),
                            "recipient": Counter(),
                            "combined": Counter(),
                        },
                    )
                    old_initiator = parsed["oldBalInitiator"]
                    new_initiator = parsed["newBalInitiator"]
                    old_recipient = parsed["oldBalRecipient"]
                    new_recipient = parsed["newBalRecipient"]
                    initiator_pattern = _delta_pattern(
                        old_initiator, new_initiator, amount
                    )
                    recipient_pattern = _delta_pattern(
                        old_recipient, new_recipient, amount
                    )
                    patterns["initiator"][initiator_pattern] += 1
                    patterns["recipient"][recipient_pattern] += 1
                    conserved = math.isclose(
                        old_initiator + old_recipient,
                        new_initiator + new_recipient,
                        abs_tol=max(0.02, abs(amount) * 2e-9),
                    )
                    combined_pattern = "conserved" if conserved else "other"
                    patterns["combined"][combined_pattern] += 1
                    balance_pattern_labels["initiator"].setdefault(
                        initiator_pattern, Counter()
                    )[label] += 1
                    balance_pattern_labels["recipient"].setdefault(
                        recipient_pattern, Counter()
                    )[label] += 1
                    balance_pattern_labels["combined"].setdefault(
                        combined_pattern, Counter()
                    )[label] += 1

                if (
                    progress_every
                    and progress
                    and data_rows % progress_every == 0
                ):
                    progress(data_rows)
    finally:
        duplicate_tracker.close()

    majority_candidates = {
        column: state["candidate"] for column, state in majority_votes.items()
    }
    majority_counts = _verify_majority_candidates(
        csv_path, encoding, columns, majority_candidates
    )

    column_statistics: dict[str, dict[str, Any]] = {}
    near_constant_columns: list[dict[str, Any]] = []
    for column in columns:
        non_null = valid_rows - null_counts[column]
        if column in exact_distinct:
            unique_count: int | None = len(exact_distinct[column])
            unique_note = "exact"
        elif column in distinct_overflow:
            unique_count = None
            unique_note = f"more than {DISTINCT_CAP:,}; not retained"
        else:
            unique_count = len(capped_distinct[column])
            unique_note = "exact"

        candidate = majority_candidates[column]
        candidate_count = majority_counts[column]
        candidate_rate = candidate_count / non_null if non_null else 0.0
        dominant_value = candidate if candidate_rate >= 0.5 else None
        dominant_count = candidate_count if dominant_value is not None else None
        dominant_rate = candidate_rate if dominant_value is not None else None

        stats: dict[str, Any] = {
            "inferred_type": _inferred_type(type_states[column]),
            "null_count": null_counts[column],
            "null_rate": null_counts[column] / valid_rows if valid_rows else 0.0,
            "unique_count": unique_count,
            "unique_count_note": unique_note,
            "examples": examples[column],
            "dominant_value_if_majority": dominant_value,
            "dominant_count": dominant_count,
            "dominant_rate": dominant_rate,
        }
        if column in NUMERIC_COLUMNS:
            stats["minimum"] = numeric_min[column]
            stats["maximum"] = numeric_max[column]
            stats["invalid_numeric_count"] = invalid_numeric_counts[column]
            stats["non_finite_count"] = non_finite_counts[column]
        column_statistics[column] = stats

        if unique_count == 1 or (dominant_rate is not None and dominant_rate >= 0.99):
            near_constant_columns.append(
                {
                    "column": column,
                    "dominant_value": dominant_value,
                    "dominant_rate": dominant_rate,
                    "unique_count": unique_count,
                }
            )

    fraud_rows = label_counts.get("1", 0)
    legitimate_rows = label_counts.get("0", 0)
    fraud_percentage = fraud_rows / valid_rows * 100 if valid_rows else 0.0
    expected = PAPER_DATASET_V1_EXPECTATIONS
    paper_v1_matches = (
        data_rows == expected["data_rows"]
        and valid_rows == expected["data_rows"]
        and legitimate_rows == expected["legitimate_rows"]
        and fraud_rows == expected["fraud_rows"]
    )

    return {
        "artifact": {
            "filename": csv_path.name,
            "byte_size": csv_path.stat().st_size,
            "sha256": sha256_file(csv_path),
            "encoding": encoding,
            "utf8_bom": has_utf8_bom,
            "header": list(columns),
            "column_count": len(columns),
        },
        "rows": {
            "data_row_count": data_rows,
            "valid_row_count": valid_rows,
            "malformed_row_count": malformed_rows,
            "duplicate_row_count": duplicate_rows,
            "duplicate_method": "SHA-256 fingerprints of canonical parsed rows in a temporary on-disk index",
        },
        "labels": {
            "counts": dict(sorted(label_counts.items())),
            "legitimate_count": legitimate_rows,
            "fraud_count": fraud_rows,
            "fraud_percentage": fraud_percentage,
            "unexpected_values": sorted(set(label_counts) - {"0", "1"}),
        },
        "transaction_types": dict(sorted(transaction_type_counts.items())),
        "label_counts_by_transaction_type": {
            transaction_type: dict(sorted(counts.items()))
            for transaction_type, counts in sorted(
                label_counts_by_transaction_type.items()
            )
        },
        "columns": column_statistics,
        "quality": {
            "non_positive_amount_count": non_positive_amount_count,
            "invalid_numeric_counts": dict(sorted(invalid_numeric_counts.items())),
            "non_finite_counts": dict(sorted(non_finite_counts.items())),
            "negative_balance_counts": {
                column: negative_balance_counts[column] for column in BALANCE_COLUMNS
            },
            "negative_balance_label_counts": {
                column: dict(sorted(negative_balance_labels[column].items()))
                for column in BALANCE_COLUMNS
            },
            "any_negative_balance_label_counts": dict(
                sorted(any_negative_balance_labels.items())
            ),
            "near_constant_columns": near_constant_columns,
            "balance_delta_patterns_by_type": {
                transaction_type: {
                    party: dict(sorted(counts.items()))
                    for party, counts in parties.items()
                }
                for transaction_type, parties in sorted(balance_patterns.items())
            },
            "balance_pattern_label_counts": {
                party: {
                    pattern: dict(sorted(counts.items()))
                    for pattern, counts in sorted(patterns.items())
                }
                for party, patterns in balance_pattern_labels.items()
            },
        },
        "temporal": {
            "step_min": min(step_values) if step_values else None,
            "step_max": max(step_values) if step_values else None,
            "unique_step_count": len(step_values),
            "invalid_step_rows": invalid_step_rows,
            "out_of_order_transitions": out_of_order_transitions,
            "chronologically_non_decreasing": out_of_order_transitions == 0,
            "steps_with_fraud": sum(
                counts.get("1", 0) > 0 for counts in label_counts_by_step.values()
            ),
            "first_step_with_fraud": min(
                (
                    step
                    for step, counts in label_counts_by_step.items()
                    if counts.get("1", 0) > 0
                ),
                default=None,
            ),
            "last_step_with_fraud": max(
                (
                    step
                    for step, counts in label_counts_by_step.items()
                    if counts.get("1", 0) > 0
                ),
                default=None,
            ),
            "candidate_whole_step_windows_60_20_20": _candidate_temporal_windows(
                step_values, label_counts_by_step
            ),
            "candidate_windows_purpose": "feasibility summary only; not a committed modeling split",
        },
        "entities": {
            "initiator_cardinality": len(initiator_activity),
            "recipient_cardinality": len(recipient_activity),
            "identifier_role_overlap": len(
                set(initiator_activity).intersection(recipient_activity)
            ),
            "initiators_with_multiple_rows": sum(
                activity[0] > 1 for activity in initiator_activity.values()
            ),
            "recipients_with_multiple_rows": sum(
                activity[0] > 1 for activity in recipient_activity.values()
            ),
            "initiators_seen_at_multiple_steps": sum(
                activity[3] for activity in initiator_activity.values()
            ),
            "recipients_seen_at_multiple_steps": sum(
                activity[3] for activity in recipient_activity.values()
            ),
            "initiator_label_profile": _entity_label_profile(initiator_activity),
            "recipient_label_profile": _entity_label_profile(recipient_activity),
        },
        "paper_dataset_v1_comparison": {
            "published_expectations": expected,
            "calculated_values_match": paper_v1_matches,
        },
    }


def write_json_report(result: dict[str, Any], output_path: str | Path) -> None:
    """Write an audit result as stable, human-readable JSON."""

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--work-directory", type=Path, default=Path("data/interim"))
    args = parser.parse_args(argv)

    result = audit_csv(
        args.csv_path,
        work_directory=args.work_directory,
        progress_every=250_000,
        progress=lambda rows: print(f"audited {rows:,} data rows", flush=True),
    )
    if args.output:
        write_json_report(result, args.output)
        print(f"wrote audit report to {args.output}")
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
