# Stage 4B: deterministic local canonical pipeline

## Boundary

Implemented: approved artifact verification, strict parsing, typed canonical records,
deterministic lineage, local canonical CSV, read-back validation, reconciliation,
and completed-run manifest. No model features, historical means, train/validation/test
materialisation, PostgreSQL integration, models or services are implemented here.

Stage 3's schema, transfer-only scoring population, Core/Enhanced tiers, forbidden
predictive inputs, and evaluation boundaries are unchanged. All transaction types
remain in the canonical layer. The label is retained as a target and post-balances
for reconciliation, not exposed as features. Stage 4C must establish a separate
unlabelled history interface; it must not treat this canonical CSV as a model matrix.

## Source and immutable evidence

The production CLI accepts only the approved artifact in the
[provenance record](data-provenance.md):

- `synthetic_mobile_money_transaction_dataset.csv`, 156,564,413 bytes;
- SHA-256 `da951eb95735da96271740a3e66b676b342d3831ce3111cd19dbfa020d3bd0a7`;
- Mendeley repository **Version 2**, DOI `10.17632/zhj366m53p.2`;
- independently matched to **paper-defined dataset version 1**, not inferred from
  the repository version;
- acquired 2026-09-05 under **CC BY 4.0**, separately from the code's MIT licence.

The source remains read-only. The gate checks filename, size and SHA-256 before
parsing, then hashes the bytes actually supplied to the UTF-8 decoder during
parsing. Before accepting that pass, it compares the consumed digest/size and the
open file/path identity, size and modification time. Replacement or modification
causes failure. The decoded records must therefore originate from the approved
bytes, rather than from an unverified later reopening of the source.

The fixture-level Python API accepts an explicit `ArtifactContract` so tests need
no real dataset. The CLI has no override or skip-verification option. Supporting a
different production artifact requires an explicitly reviewed provenance contract.

## Run from the repository root

After installing the project using the README development setup:

```powershell
python -m transactionshield.pipeline data/raw/synthetic_mobile_money_transaction_dataset.csv `
  --output-directory data/interim/canonical/stage4b
```

Equivalent installed entry point: `transactionshield-canonical` with the same
arguments. For an existing Python environment without installing the package:

```powershell
$env:PYTHONPATH = "src"
python -B -m transactionshield.pipeline data/raw/synthetic_mobile_money_transaction_dataset.csv `
  --output-directory data/interim/canonical/stage4b
```

No network, database, download or runtime dependency is required. The source must
already exist locally. CLI destinations must be new run directories below this
repository's ignored `data/interim/` or `data/processed/`. Existing output is never
overwritten, and output cannot contain the source or be inside its directory.

## Module responsibilities

| Module | Responsibility |
|---|---|
| `canonical.py` | Exact header, strict records, semantic checks, typed representation and ordered schema |
| `contracts.py` | Shared decimal grammar, transaction-type domain and frozen UUIDv5 rules |
| `validation.py` | Approved artifact metadata, consumed-byte gate and bounded reconciliation |
| `materialisation.py` | Deterministic CSV/JSON writing and typed read-back verification |
| `pipeline.py` | Orchestration, implementation identity, publication and CLI |

The existing permissive `ingestion.py` inspection API is unchanged. It must not be
used as a substitute for production canonical validation.

## Strict source rules

- Require the ten verified header fields in their exact sequence. No stripping,
  extra, missing, duplicate, reordered or renamed fields. UTF-8 is strict; a BOM
  is not stripped into validity because the approved artifact has none.
- Use strict CSV parsing and exact row width. Errors include logical source row
  and column/record context. Quoted commas, quotes and embedded newlines remain
  valid CSV; lineage counts logical records, not physical lines.
- Steps are integer literals representing non-negative PostgreSQL `INTEGER`
  values. The storage range is enforced, not the observed maximum of 143.
- Transaction types use the five frozen exact values; labels must be exactly
  `0` or `1`. All types are retained without eligibility filtering.
- IDs must be nonempty and not whitespace-only. Otherwise retain text exactly,
  including leading zeros, mixed formats, surrounding whitespace and Unicode.
  No sample-specific length or pattern constraint is added.
- Monetary fields use the shared plain-decimal grammar: optional sign, digits,
  optionally a decimal point followed by digits. Parse directly to `Decimal`;
  reject exponent notation, whitespace, invalid and non-finite values.
- `amount > 0`; negative balances and signed zero balances remain valid. No
  float conversion, rounding, clipping, defaulting, imputation or row dropping.
- Source row numbers must be actual Python integers, excluding booleans/floats,
  from 2 through the PostgreSQL `BIGINT` maximum. The pipeline assigns contiguous
  numbers; UUIDv5 is derived from the frozen namespace, checksum and row number.

## Canonical CSV format, version 1

Fields follow the existing canonical SQL mapping, in this exact order:

```text
transaction_id,artifact_id,source_row_number,step,transaction_type,amount,initiator_id,initiator_balance_before,initiator_balance_after,recipient_id,recipient_balance_before,recipient_balance_after,is_fraud
```

- UTF-8 without BOM; LF record terminators; comma delimiter; standard minimal
  double-quote escaping. Embedded source identifier line breaks remain unchanged.
- Source order, with ascending logical source row numbers. This is reproducible
  storage order, not a claim of within-step event order.
- UUIDs use their standard lowercase string form. Integers use decimal text.
- Monetary rendering is the **exact validated source lexeme**. The typed record
  retains both its `Decimal` value and its original literal. Thus `+0001.200`
  remains `+0001.200`, and `-0.00` remains `-0.00`. This preserves more than numeric
  equality: sign spelling, leading zeros and scale are lossless too. Ambient
  Decimal precision does not affect parsing or rendering. No mean policy exists.
- No nulls in canonical source fields. Explicit schema types, nullability and
  roles are recorded in the manifest; CSV itself is not a typed storage engine.
- Target and lineage are explicit columns. They are not a feature allowlist.

## Reconciliation and publication

The writer streams records and tracks only counters and step extrema. Its digest
records exact emitted UTF-8 bytes. A second streaming pass reads the output,
reparses all payload fields, rederives identities, checks contiguous lineage and
rendering, and independently reconciles counts. The stored size and SHA-256 must
also match the writer's byte stream.

The full-artifact gate requires the approved 1,720,181 rows, 1,544,663 legitimate,
175,518 fraud, exact counts for all five types, steps 0 through 143 as extrema,
and zero chronological regressions. These are integrity checks against existing
audit evidence, not new test-label exploration. It does not silently sort or alter
rows to make discrepancies disappear. The source hash also binds to the prior
duplicate/missing-value audit; this stage does not repeat every exploratory audit.

All work is first written into a uniquely named sibling `.incomplete-...`
directory. The CSV initially has an `.incomplete` suffix. After validation and
implementation-stability checks, the manifest is written and the directory is
renamed to the requested final name on the same filesystem. Consumers must use
only a final run directory with a completed manifest, never staging directories.

Ordinary failures retain an incomplete directory with `failure.json` and any
partial CSV, but no completed manifest. If a crash, interruption or disk failure
prevents reporting, the incomplete directory itself still indicates failure.
There is no automatic resume or cleanup of previous runs. Publication provides
atomic visibility on the local filesystem, not a database transaction or a claim
of power-loss durability. Use separate destination names for separate runs.

## Deterministic manifest

`manifest.json` contains:

- full approved source identity, version terminology, attribution and expectations;
- pipeline/schema versions and source/consumed-byte/read-back gate results;
- canonical row, class, type and ordering reconciliation;
- ordered output schema, types, roles and nullability;
- canonical output filename, size and SHA-256;
- exact serialisation configuration;
- Git HEAD when available and an implementation SHA-256 over package Python files
  and `pyproject.toml`, with ordered relative names and byte lengths included.

Git HEAD alone does not identify uncommitted implementation changes. The separate
implementation digest binds those bytes; its constituent filenames are recorded.
The pipeline fails if this identity changes during a run. JSON is UTF-8, LF,
sorted-key, indented and excludes volatile paths, timestamps and elapsed time.
Elapsed time and the manifest's SHA-256 are printed by the CLI, not embedded in
the manifest itself. Its hash is external to avoid a self-referential digest.

To check determinism, run with a second new destination using the same source,
code and configuration, then compare SHA-256 for both `canonical.csv` files and
both `manifest.json` files. A subsequent code revision may legitimately change the
manifest while identical source/format rules still produce the same canonical CSV.

## Verification and limitations

Run `python -m pytest`. New tests use small synthetic fixtures, created and removed
under ignored `data/interim/`; they do not depend on the real raw CSV. Tests cover
strict schema/semantics, lossless rendering, identity, artifact gates, mutations,
late failures, publication, read-back checks and repeated deterministic outputs.

Memory is bounded with respect to transaction count: only the current record,
I/O buffers and fixed-domain counters are retained. Full parsing plus independent
read-back deliberately trades additional sequential CPU/I/O for verification.

The six-day synthetic horizon and the paper's 720-step discrepancy are unchanged.
No historical features, historical means, model parameters, validation thresholds
or test evaluation are computed. These remain later-stage work under the frozen
contracts.

## Full-artifact acceptance recorded 2026-09-07

Two complete runs, each including independent typed read-back, passed against the
approved raw artifact using Python 3.12.8. Both retained every source transaction.

| Measurement | Independently verified Stage 4B result |
|---|---:|
| Canonical rows | 1,720,181 |
| Legitimate / fraud | 1,544,663 / 175,518 |
| DEBIT | 5,392 |
| DEPOSIT | 384,431 |
| PAYMENT | 667,245 |
| TRANSFER | 569,328 |
| WITHDRAWAL | 93,785 |
| Step extrema / chronological regressions | 0 through 143 / 0 |
| Canonical CSV bytes, each run | 296,508,244 |
| Elapsed time, first / repeat | 86.522 s / 84.903 s |
| First-run peak process working set | 26,439,680 bytes (approximately 25.2 MiB) |

Canonical CSV SHA-256, identical in both runs:
`0e5ced75fc3ca0787445a8f7f616f4eb7200c2da3bcf39d5e55d081a15bd14f2`.

Manifest SHA-256, identical in both runs:
`b58a5cd576d95eb6ed720e8bebd26e51d44af6b514ad1236898d40bc2f780ea7`.

The manifests record base Git HEAD
`fd4e080bb8ae06e4d51b148f6cf428fc942cc5ad` and implementation digest
`1bebb5a849207dd504866c9b24037543847af5fbf0ac572dfa3088c0d193cfb1`.
Stage 4B was uncommitted during acceptance; the implementation digest identifies
the actual package/configuration bytes, not just that earlier Stage 3 commit.
Output directories are `data/interim/canonical/stage4b/` and
`data/interim/canonical/stage4b-repeat/`, both Git-ignored. Peak working set was
observed using Windows process counters without a new dependency; it is a local
measurement, not a cross-machine performance guarantee.
