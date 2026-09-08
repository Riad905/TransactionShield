"""Structural Stage 4C acceptance only: summaries/hashes, never feature files."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from collections.abc import Iterable, Sequence
from decimal import Decimal
from pathlib import Path

from transactionshield.canonical import CanonicalTransaction, iter_canonical_records
from transactionshield.contracts import EVALUATION_WINDOWS, evaluation_partition
from transactionshield.features import (
    CORE_FEATURE_NAMES, ENHANCED_ADDITIONAL_NAMES, FEATURE_CONTRACT_VERSION,
    FeatureExample, HistoryEngine, iter_feature_examples,
)
from transactionshield.materialisation import write_json
from transactionshield.pipeline import REPOSITORY_ROOT, code_identity
from transactionshield.validation import APPROVED_ARTIFACT, IntegrityError, verified_source

APPROVED_PARTITION_COUNTS = {"train": 375_732, "validation": 94_503, "test": 99_093}


def _numeric_token(value: Decimal | int | None) -> object:
    """Exact numeric equality token for diagnostics, NOT a persistent feature format."""

    if not isinstance(value, Decimal):
        return value
    sign, digits, exponent = value.as_tuple()
    coefficient = "".join(str(digit) for digit in digits)
    if not coefficient.strip("0"):
        return [0, "0", 0]
    trimmed = coefficient.rstrip("0")
    return [sign, trimmed, exponent + len(coefficient) - len(trimmed)]


def _diagnostic_bytes(example: FeatureExample, *, enhanced: bool) -> bytes:
    values = [_numeric_token(getattr(example.core, name)) for name in CORE_FEATURE_NAMES]
    if enhanced:
        assert example.enhanced is not None
        values.extend(_numeric_token(getattr(example.enhanced, name))
                      for name in ENHANCED_ADDITIONAL_NAMES)
    # Lineage binds the diagnostic to transactions, but is never a predictor.
    return (json.dumps([str(example.lineage.transaction_id), values],
                       separators=(",", ":")) + "\n").encode("utf-8")


def validate_feature_rows(rows: Iterable[CanonicalTransaction]) -> dict[str, object]:
    """Consume typed rows without reading labels; retain counters, never examples."""

    history = HistoryEngine()
    consumed = 0
    emitted = 0
    partitions: Counter[str] = Counter()
    null_counts: Counter[str] = Counter()
    zero_counts: Counter[str] = Counter()
    core_digest = hashlib.sha256()
    enhanced_digest = hashlib.sha256()

    def counted_rows() -> Iterable[CanonicalTransaction]:
        nonlocal consumed
        for row in rows:
            consumed += 1
            yield row

    for example in iter_feature_examples(counted_rows(), enhanced=True, engine=history):
        emitted += 1
        partitions[evaluation_partition(example.lineage.step)] += 1
        for name in CORE_FEATURE_NAMES:
            value = getattr(example.core, name)
            if value is None:
                null_counts[name] += 1
            elif value == 0:
                zero_counts[name] += 1
        core_digest.update(_diagnostic_bytes(example, enhanced=False))
        enhanced_digest.update(_diagnostic_bytes(example, enhanced=True))
    schema = [{"name": name, "type": "integer" if name.endswith("count") else "Decimal",
               "nullable": name.endswith(("mean", "max"))} for name in CORE_FEATURE_NAMES]
    return {
        "feature_contract_version": FEATURE_CONTRACT_VERSION,
        "source_rows_consumed": consumed,
        "eligible_examples_emitted": emitted,
        "partition_counts": {name: partitions[name] for name, _, _ in EVALUATION_WINDOWS},
        "core_schema": schema,
        "enhanced_additional_schema": [{"name": name, "type": "Decimal", "nullable": False}
                                       for name in ENHANCED_ADDITIONAL_NAMES],
        "null_counts": {name: null_counts[name] for name in CORE_FEATURE_NAMES},
        "zero_counts": {name: zero_counts[name] for name in CORE_FEATURE_NAMES},
        "chronological_regressions": 0,  # A regression raises; no successful report exists.
        "state": history.state_statistics(),
        "core_diagnostic_sha256": core_digest.hexdigest(),
        "enhanced_diagnostic_sha256": enhanced_digest.hexdigest(),
        "diagnostic_hash_scope": "numeric feature values plus transaction identity in replay order; not a file format",
    }


def validate_artifact(path: Path) -> dict[str, object]:
    implementation = code_identity()
    with verified_source(path.resolve(strict=True), APPROVED_ARTIFACT) as source:
        report = validate_feature_rows(iter_canonical_records(source, APPROVED_ARTIFACT.sha256))
    if (report["source_rows_consumed"] != APPROVED_ARTIFACT.row_count
            or report["partition_counts"] != APPROVED_PARTITION_COUNTS
            or report["eligible_examples_emitted"] != sum(APPROVED_PARTITION_COUNTS.values())):
        raise IntegrityError("feature acceptance counts differ from frozen population/splits")
    if implementation != code_identity():
        raise IntegrityError("implementation changed during feature validation")
    return {"status": "passed", "source_sha256": APPROVED_ARTIFACT.sha256,
            "source_validation": "precheck, consumed-byte digest and stability checks passed",
            "code": implementation, **report}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--report-output", type=Path,
                        help="optional summary JSON only, under ignored data/interim/")
    args = parser.parse_args(argv)
    if args.report_output:
        output = args.report_output.resolve()
        root = (REPOSITORY_ROOT / "data" / "interim").resolve()
        if not output.is_relative_to(root) or output == root or output.exists():
            parser.error("report must be a new file below data/interim/")
    started = time.perf_counter()
    try:
        report = validate_artifact(args.source)
        if args.report_output:
            output.parent.mkdir(parents=True, exist_ok=True)
            write_json(output, report)
    except (ValueError, OSError) as error:
        print(f"Feature validation failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"elapsed_seconds": round(time.perf_counter() - started, 3),
                      "validation": report}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
