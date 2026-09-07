"""Stage 4B: verified raw artifact to reconciled local canonical records only."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from transactionshield.audit import sha256_file
from transactionshield.canonical import CANONICAL_SCHEMA, SCHEMA_VERSION, iter_canonical_records
from transactionshield.materialisation import (
    SERIALISATION, verify_canonical_csv, write_canonical_csv, write_json,
)
from transactionshield.validation import (
    APPROVED_ARTIFACT, ArtifactContract, IntegrityError, Reconciliation, verified_source,
)

PIPELINE_VERSION = "transactionshield.canonical-pipeline.v1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def code_identity() -> dict[str, object]:
    """Record HEAD when available plus exact implementation bytes, including edits."""

    package = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    files = [(f"transactionshield/{p.name}", p) for p in sorted(package.glob("*.py"))]
    configuration = REPOSITORY_ROOT / "pyproject.toml"
    if configuration.is_file():
        files.append(("pyproject.toml", configuration))
    for name, path in files:
        payload = path.read_bytes()
        digest.update(name.encode("utf-8") + b"\0" + str(len(payload)).encode("ascii") + b"\0")
        digest.update(payload)
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT,
            capture_output=True, text=True, check=True, timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        revision = None
    return {"git_head": revision, "implementation_sha256": digest.hexdigest(),
            "implementation_files": [name for name, _ in files]}


def _safe_destination(source: Path, destination: Path) -> None:
    if (destination == source or source.is_relative_to(destination)
            or destination.is_relative_to(source.parent)):
        raise ValueError("output must not overwrite/contain the source or be inside its directory")
    if destination.exists():
        raise FileExistsError(f"output already exists; choose a new run directory: {destination}")


def run_canonical_pipeline(
    source: str | Path,
    output_directory: str | Path,
    *,
    contract: ArtifactContract = APPROVED_ARTIFACT,
) -> dict[str, object]:
    """Publish a new run directory only after all gates pass.

    Explicit alternate contracts support isolated fixtures; the CLI always uses
    APPROVED_ARTIFACT and offers no checksum/provenance override.
    """

    source = Path(source).resolve(strict=True)
    destination = Path(output_directory).resolve()
    _safe_destination(source, destination)
    implementation = code_identity()
    staging: Path | None = None
    try:
        with verified_source(source, contract) as stream:
            destination.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(
                prefix=f".{destination.name}.incomplete-", dir=destination.parent,
            ))
            incomplete = staging / "canonical.csv.incomplete"
            counts = Reconciliation()
            output = write_canonical_csv(
                iter_canonical_records(stream, contract.sha256), incomplete, counts,
            )
        # verified_source's exit has now checked the actual consumed bytes.
        counts.verify(contract)
        verified_counts = verify_canonical_csv(incomplete, output, contract)
        if counts.as_dict() != verified_counts.as_dict():
            raise IntegrityError("input/output reconciliation mismatch")
        if implementation != code_identity():
            raise IntegrityError("implementation changed during processing")
        manifest = {
            "status": "complete",
            "pipeline_version": PIPELINE_VERSION,
            "schema_version": SCHEMA_VERSION,
            "source": asdict(contract),
            "code": implementation,
            "configuration": SERIALISATION,
            "validation": {"source_precheck": "passed", "consumed_source_bytes": "passed",
                           "source_stability": "passed", "output_readback": "passed",
                           "reconciliation": "passed"},
            "counts": counts.as_dict(),
            "output": {"filename": "canonical.csv", **output,
                       "schema": [{"name": name, "type": kind, "role": role,
                                   "nullable": False} for name, kind, role in CANONICAL_SCHEMA]},
        }
        incomplete.rename(staging / "canonical.csv")
        write_json(staging / "manifest.json", manifest)
        # Staging is a sibling on the same filesystem. No output is replaced.
        if destination.exists():
            raise FileExistsError(f"output appeared during run: {destination}")
        staging.rename(destination)
        return manifest
    except Exception as error:
        if staging is not None and staging.exists():
            try:
                (staging / "manifest.json").unlink(missing_ok=True)
                write_json(staging / "failure.json", {
                    "status": "failed", "error_type": type(error).__name__,
                    "message": str(error), "source_sha256": contract.sha256,
                })
            except OSError as report_error:
                error.add_note(f"Could not persist failure report in {staging}: {report_error}")
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args(argv)
    destination = args.output_directory.resolve()
    permitted = [REPOSITORY_ROOT / "data" / part for part in ("interim", "processed")]
    if not any(destination.is_relative_to(root.resolve()) and destination != root.resolve()
               for root in permitted):
        parser.error("output must be a run directory under data/interim/ or data/processed/")
    started = time.perf_counter()
    try:
        manifest = run_canonical_pipeline(args.source, destination)
    except (ValueError, OSError) as error:
        print(f"Canonical run failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"output_directory": str(destination), "counts": manifest["counts"],
                      "output": {k: v for k, v in manifest["output"].items() if k != "schema"},
                      "manifest_sha256": sha256_file(destination / "manifest.json"),
                      "elapsed_seconds": round(time.perf_counter() - started, 3)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
