import csv
import hashlib
import io
import json
import tempfile
from collections import Counter
from dataclasses import replace
from decimal import localcontext
from pathlib import Path

import pytest

from transactionshield import pipeline
from transactionshield.audit import sha256_file
from transactionshield.canonical import CANONICAL_COLUMNS, CanonicalValidationError
from transactionshield.ingestion import MOMTSIM_PAPER_DATASET_V1_COLUMNS
from transactionshield.materialisation import verify_canonical_csv
from transactionshield.validation import APPROVED_ARTIFACT, IntegrityError


@pytest.fixture
def workspace():
    # Keep all test IO inside the repository's ignored generated-data area.
    parent = Path(__file__).resolve().parents[1] / "data" / "interim"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stage4b-test-", dir=parent) as directory:
        yield Path(directory)


def artifact(workspace, rows=None, payload=None):
    rows = rows or [
        ["0", "TRANSFER", "+0001.200", " 001 ", "-10.000", "-0.00", 'B,"x"', "0", "1", "1"],
        ["1", "PAYMENT", "2.0", "002", "0", "-2", "A\nB", "1", "3", "0"],
    ]
    if payload is None:
        text = io.StringIO(newline="")
        writer = csv.writer(text, lineterminator="\r\n")
        writer.writerow(MOMTSIM_PAPER_DATASET_V1_COLUMNS)
        writer.writerows(rows)
        payload = text.getvalue().encode("utf-8")
    raw = workspace / "raw"
    raw.mkdir(exist_ok=True)
    source = raw / APPROVED_ARTIFACT.filename
    source.write_bytes(payload)
    types = Counter(row[1] for row in rows)
    labels = Counter(row[-1] for row in rows)
    contract = replace(
        APPROVED_ARTIFACT, byte_size=len(payload), sha256=hashlib.sha256(payload).hexdigest(),
        row_count=len(rows), legitimate_count=labels["0"], fraud_count=labels["1"],
        transaction_type_counts=tuple(sorted(types.items())),
        step_min=min(int(row[0]) for row in rows), step_max=max(int(row[0]) for row in rows),
    )
    return source, contract


def test_success_and_deterministic_materialisation(workspace):
    source, contract = artifact(workspace)
    original = source.read_bytes()
    first = workspace / "first"
    second = workspace / "second"
    manifest = pipeline.run_canonical_pipeline(source, first, contract=contract)
    with localcontext() as context:
        context.prec = 2
        repeated = pipeline.run_canonical_pipeline(source, second, contract=contract)
    assert manifest == repeated
    for filename in ("canonical.csv", "manifest.json"):
        assert (first / filename).read_bytes() == (second / filename).read_bytes()
    assert source.read_bytes() == original
    assert manifest["source"]["sha256"] == contract.sha256
    assert manifest["source"]["repository_version"] == 2
    assert manifest["source"]["paper_dataset_version"] == 1
    assert manifest["counts"]["canonical_row_count"] == 2
    assert manifest["counts"]["transaction_type_counts"] == {"PAYMENT": 1, "TRANSFER": 1}
    assert manifest["output"]["sha256"] == sha256_file(first / "canonical.csv")
    assert manifest["output"]["byte_size"] == (first / "canonical.csv").stat().st_size
    assert manifest["code"]["implementation_sha256"]
    with (first / "canonical.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream))
    assert rows[0] == list(CANONICAL_COLUMNS)
    assert rows[1][5] == "+0001.200"
    assert rows[1][6] == " 001 "
    assert rows[1][7:9] == ["-10.000", "-0.00"]
    assert rows[2][9] == "A\nB"
    assert b"\r\n" not in (first / "canonical.csv").read_bytes()
    assert not list(workspace.glob(".*.incomplete-*"))


@pytest.mark.parametrize(("change", "message"), [
    ({"sha256": "0" * 64}, "SHA-256"), ({"byte_size": 1}, "size"),
    ({"filename": "different.csv"}, "filename"),
])
def test_artifact_gate_failures_create_no_outputs(workspace, change, message):
    source, contract = artifact(workspace)
    output = workspace / "run"
    with pytest.raises(IntegrityError, match=message):
        pipeline.run_canonical_pipeline(source, output, contract=replace(contract, **change))
    assert not output.exists()
    assert not list(workspace.glob(".*.incomplete-*"))


def test_cli_cannot_accept_fixture_as_approved_source(workspace, capsys):
    source, _ = artifact(workspace)
    output = workspace / "run"
    assert pipeline.main([str(source), "--output-directory", str(output)]) == 1
    assert "size mismatch" in capsys.readouterr().err


@pytest.mark.parametrize("target", ["source", "raw", "raw_child", "ancestor"])
def test_raw_source_cannot_be_overwritten(workspace, target):
    source, contract = artifact(workspace)
    original = source.read_bytes()
    output = {"source": source, "raw": source.parent,
              "raw_child": source.parent / "output", "ancestor": workspace}[target]
    with pytest.raises(ValueError, match="source"):
        pipeline.run_canonical_pipeline(source, output, contract=contract)
    assert source.read_bytes() == original


def test_existing_run_cannot_be_overwritten(workspace):
    source, contract = artifact(workspace)
    output = workspace / "run"
    pipeline.run_canonical_pipeline(source, output, contract=contract)
    before = (output / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        pipeline.run_canonical_pipeline(source, output, contract=contract)
    assert (output / "manifest.json").read_bytes() == before


def assert_failed_only(workspace, output):
    assert not output.exists()
    incomplete = list(workspace.glob(".*.incomplete-*"))
    assert len(incomplete) == 1
    assert not (incomplete[0] / "manifest.json").exists()
    failure = json.loads((incomplete[0] / "failure.json").read_text())
    assert failure["status"] == "failed"
    return failure


def test_late_semantic_failure_never_publishes(workspace):
    rows = [["0", "TRANSFER", "1", "A", "0", "-1", "B", "0", "1", "1"],
            ["1", "PAYMENT", "0", "A", "0", "0", "B", "0", "0", "0"]]
    source, contract = artifact(workspace, rows)
    output = workspace / "run"
    with pytest.raises(CanonicalValidationError, match="row 3, amount"):
        pipeline.run_canonical_pipeline(source, output, contract=contract)
    assert "row 3, amount" in assert_failed_only(workspace, output)["message"]


def test_reconciliation_discrepancy_never_publishes(workspace):
    source, contract = artifact(workspace)
    output = workspace / "run"
    with pytest.raises(IntegrityError, match="reconciliation"):
        pipeline.run_canonical_pipeline(source, output, contract=replace(contract, row_count=3))
    assert_failed_only(workspace, output)


def test_source_mutation_after_gate_detected(workspace, monkeypatch):
    source, contract = artifact(workspace)
    original_writer = pipeline.write_canonical_csv

    def mutate_then_write(*args):
        source.write_bytes(source.read_bytes().replace(b"+0001.200", b"+0001.201"))
        return original_writer(*args)

    monkeypatch.setattr(pipeline, "write_canonical_csv", mutate_then_write)
    output = workspace / "run"
    with pytest.raises(IntegrityError, match="source"):
        pipeline.run_canonical_pipeline(source, output, contract=contract)
    assert_failed_only(workspace, output)


def test_source_metadata_change_after_consumption_detected(workspace, monkeypatch):
    import os
    source, contract = artifact(workspace)
    original_writer = pipeline.write_canonical_csv

    def touch_after_write(*args):
        result = original_writer(*args)
        stat = source.stat()
        os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        return result

    monkeypatch.setattr(pipeline, "write_canonical_csv", touch_after_write)
    output = workspace / "run"
    with pytest.raises(IntegrityError, match="source changed"):
        pipeline.run_canonical_pipeline(source, output, contract=contract)
    assert_failed_only(workspace, output)


@pytest.mark.parametrize("payload", [b"\xff", b"\xef\xbb\xbfstep,other\n", b""])
def test_bad_encoding_bom_or_empty_source_fail_closed(workspace, payload):
    source, contract = artifact(workspace, payload=payload)
    output = workspace / "run"
    with pytest.raises(CanonicalValidationError):
        pipeline.run_canonical_pipeline(source, output, contract=contract)
    assert_failed_only(workspace, output)


def test_canonical_output_tampering_is_detected(workspace):
    source, contract = artifact(workspace)
    output = workspace / "run"
    manifest = pipeline.run_canonical_pipeline(source, output, contract=contract)
    path = output / "canonical.csv"
    path.write_bytes(path.read_bytes().replace(b"+0001.200", b"+0001.201"))
    with pytest.raises(IntegrityError, match="bytes"):
        verify_canonical_csv(path, manifest["output"], contract)


def test_ordering_discrepancy_is_not_silently_sorted(workspace):
    rows = [["1", "TRANSFER", "1", "A", "0", "-1", "B", "0", "1", "1"],
            ["0", "PAYMENT", "2", "A", "0", "-2", "B", "0", "2", "0"]]
    source, contract = artifact(workspace, rows)
    output = workspace / "run"
    with pytest.raises(IntegrityError, match="reconciliation"):
        pipeline.run_canonical_pipeline(source, output, contract=contract)
    assert_failed_only(workspace, output)


def test_publication_failure_removes_completed_manifest(workspace, monkeypatch):
    source, contract = artifact(workspace)
    original_rename = Path.rename
    output = workspace / "run"

    def fail_directory_promotion(path, target):
        if Path(target) == output:
            raise OSError("simulated publication failure")
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_directory_promotion)
    with pytest.raises(OSError, match="publication failure"):
        pipeline.run_canonical_pipeline(source, output, contract=contract)
    assert_failed_only(workspace, output)


def test_output_validation_failure_never_publishes(workspace, monkeypatch):
    source, contract = artifact(workspace)

    def reject_output(*args):
        raise IntegrityError("simulated readback failure")

    monkeypatch.setattr(pipeline, "verify_canonical_csv", reject_output)
    output = workspace / "run"
    with pytest.raises(IntegrityError, match="readback failure"):
        pipeline.run_canonical_pipeline(source, output, contract=contract)
    assert_failed_only(workspace, output)


def test_implementation_change_never_publishes(workspace, monkeypatch):
    source, contract = artifact(workspace)
    identities = iter([{"implementation_sha256": "before"}, {"implementation_sha256": "after"}])
    monkeypatch.setattr(pipeline, "code_identity", lambda: next(identities))
    output = workspace / "run"
    with pytest.raises(IntegrityError, match="implementation changed"):
        pipeline.run_canonical_pipeline(source, output, contract=contract)
    assert_failed_only(workspace, output)


def test_cli_rejects_non_generated_output(workspace):
    source, _ = artifact(workspace)
    with pytest.raises(SystemExit) as failure:
        pipeline.main([str(source), "--output-directory", str(Path(__file__).parent / "output")])
    assert failure.value.code == 2
