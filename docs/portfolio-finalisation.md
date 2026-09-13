# Portfolio finalisation: evidence and reproduction

## Verification status

Local verification: **209 passed, five PostgreSQL skips (214 collected)**.
All 25 Python files compiled. No local PostgreSQL server was installed.
**The five genuine PostgreSQL integration tests are VERIFIED IN CI.** On
2026-09-13, [run 34757283878](https://github.com/Riad905/TransactionShield/actions/runs/34757283878)
for commit `0c6574578ea904de1c41c881ce297ca7fa769685` completed successfully.
The [test job](https://github.com/Riad905/TransactionShield/actions/runs/34757283878/job/103723733491)
passed ordinary tests, the full 214-case suite, the explicit check requiring all
five database cases and zero skips, and compile/whitespace checks. Run and step
conclusions were observed through GitHub's read-only API; no SQL or test changes
were needed. **No full 1,720,181-row PostgreSQL load has been performed.**

The existing Stage 4D/4E implementation was recovered, not redesigned. Frozen
canonical/feature contracts, model families, hyperparameters, validation selection
and chronological partitions remain unchanged. Eleven controlled ranking tests
cover hand calculations, capacity rounding, stable ties, absent fraud and invalid
inputs. The earlier 198 ordinary tests are retained.

## Fixed-budget descriptive ranking

The already-selected Enhanced histogram boosting model ranks 99,093 held-out
transfers containing 29,104 fraud cases (29.370389% prevalence). These five budgets
were specified before analysis. This is **post-hoc description**, not model,
feature, threshold or capacity selection. No operational costs are assumed.

| Review budget | Reviewed | Fraud captured | Precision | Recall | Lift over prevalence |
|---|---:|---:|---:|---:|---:|
| 0.5% | 496 | 496 | 100.0000% | 1.7042% | 3.4048 |
| 1% | 991 | 901 | 90.9183% | 3.0958% | 3.0956 |
| 2% | 1,982 | 1,186 | 59.8385% | 4.0750% | 2.0374 |
| 5% | 4,955 | 2,108 | 42.5429% | 7.2430% | 1.4485 |
| 10% | 9,910 | 3,581 | 36.1352% | 12.3042% | 1.2303 |

Capacity is `ceil(test_count * budget)`, calculated with integer basis points.
Scores sort descending; stable original replay order breaks ties without labels.
This arbitrary deterministic tie policy is not evidence of within-step event
ordering and is not a predictive feature. Results at tied cutoffs can depend on
that policy. Precision = captured/reviewed; recall = captured/total fraud;
lift = precision/test prevalence. No-positive fixtures return null recall/lift.

There is strong concentration in a tiny top slice, followed by rapid dilution.
Even reviewing 10% captures only 12.30% of test fraud. Perfect top-0.5% precision
is one synthetic holdout observation, not a real-world guarantee. No budget is
recommended as optimal; no staffing, loss-prevention or ROI claim follows.

- **Discrimination:** ROC-AUC and AP summarise ranking across operating points.
  Enhanced test ROC-AUC 0.5479 is weak; AP 0.3520 only modestly exceeds prevalence
  0.2937. Core boosting AP 0.3533 is slightly higher on test; the validation-selected
  winner was not changed retrospectively.
- **Threshold classification:** the frozen validation-F1 threshold 0.1806139476
  flags 95.05% of test transfers. The fixed 0.5 reference produces 904 alerts with
  877 fraud cases: 97.01% precision but 3.01% recall. Neither threshold is claimed
  to express an operational cost policy.
- **Capacity ranking:** review a fixed number of highest scores, regardless of
  whether scores exceed 0.5. A top-0.5% budget is not a threshold of 0.5. Ranking
  enrichment does not establish probability calibration.

## Full-data deterministic replay

Recovered `artifacts/portfolio-final-1/` and repeated `artifacts/portfolio-final-2/`
both consumed 1,720,181 source rows and emitted 569,328 transfers, split
375,732 / 94,503 / 99,093. Source SHA-256:
`da951eb95735da96271740a3e66b676b342d3831ce3111cd19dbfa020d3bd0a7`.

Exact pre-float feature hashes match Stage 4C:

- Core: `256bdaa32d81e2f6c2c3ddd1780aee5b37695951d9fa63eef5e805c3952c4df5`
- Enhanced: `011f5c488f9a1ed5cc1669c1d6023e719abcff2a873e30703e6dd7fc688dafd7`

Each has 5,297 null historical means and maxima; all other feature null counts
are zero. Nine Core and two separate Enhanced fields enter a 50,100,864-byte
float64 matrix only after exact feature verification.

| Run | Source/features seconds | Total seconds | Windows peak process bytes |
|---|---:|---:|---:|
| Recovered final-1 | 111.139 | 126.435 | 486,932,480 |
| Repeated final-2 | 100.595 | 116.285 | 484,040,704 |

Both actual metrics files have SHA-256
`a3b557fe549ad7edde5a642a1a821b33f69beb2bd63eabcf92f9db708a939f06`.
Every original gate, parameter, threshold, validation/test metric, explanation
and error summary equals the earlier `artifacts/stage4e-verified/metrics.json`;
only code identity and the added ranking report differ from that earlier run.
The committed `stage4e-results.json` preserves the earlier aggregate experiment;
the new ranking table above comes from these matching finalisation runs.

Reports use explicit LF and hash actual bytes. Runtime/memory are observations,
excluded from deterministic metrics. Code identity includes package source,
project metadata and Git HEAD: the subsequent factual package-description edit
and commits change report identity, not model decisions or numerical results.
Cross-platform bitwise equivalence is not promised.

## PostgreSQL CI

Workflow: [Tests and PostgreSQL](../.github/workflows/ci.yml), triggered by main
pushes, pull requests and manual dispatch. Ubuntu hosts official `postgres:17`.
Database `transactionshield_test_ci`, user `postgres` and password `ci_only_dummy`
are disposable CI-only settings. Port 5432 maps to localhost; `pg_isready` runs
every 10 seconds with a five-second timeout and five retries. The job has a
15-minute limit and read-only repository permissions.

Python 3.12 installs `.[dev,postgres,modelling]`, runs ordinary tests, then the full
suite against PostgreSQL. JUnit inspection requires exactly five database cases
and no skipped tests. No dataset, model or database dump is transferred by CI.

The genuine tests in `tests/test_postgres_integration.py` are:

1. `test_real_schema_and_numeric_round_trip`
2. `test_real_load_reload_and_tier_separation`
3. `test_real_late_failure_rolls_back_all_tables`
4. `test_real_duplicate_and_integrity_constraints`
5. `test_real_modified_contents_are_not_silently_overwritten`

They exercise actual migrations, NUMERIC/Decimal and null round trips, relational
constraints, completion/reload, rollback, conflicting contents and server-side
read-back cursors on small fixtures. This is not full-data database acceptance.

Design references: [GitHub PostgreSQL service-container guide](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers)
and [PostgreSQL supported versions](https://www.postgresql.org/support/versioning/).

## Fresh-user reproduction

Use a repository checkout (SQL migrations are repository files) and Python 3.12.8
for the recorded numerical environment. The package supports Python 3.11+; full
CI targets Python 3.12. Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,postgres,modelling]"
$env:LOKY_MAX_CPU_COUNT = "1"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pytest -m "not postgres"
.\.venv\Scripts\python.exe -m compileall -q src tests
git diff --check
.\.venv\Scripts\python.exe -m transactionshield.modelling --source data/raw/synthetic_mobile_money_transaction_dataset.csv --output artifacts/portfolio-reproduction
Get-FileHash artifacts/portfolio-reproduction/metrics.json -Algorithm SHA256
```

Acquire the approved source using the [provenance/acquisition record](data-provenance.md)
before modelling. Existing output directories are refused. Generated
`selection.json` freezes validation decisions before test evaluation; `metrics.json`
includes ranking; `runtime.json` records timing, available memory and checksum.
Reports stay ignored; no feature matrix, predictions or serving binary is published.

For real database tests, privately set `TRANSACTIONSHIELD_TEST_DATABASE_DSN` to
a disposable database whose name starts `transactionshield_test`, then run:

```powershell
.\.venv\Scripts\python.exe -m pytest -m postgres
```

Tests refuse existing application schemas and remove only the schema they created
in that opted-in test database. Do not use valuable data. Without a server they
skip locally; CI provisions its own service and requires execution. See the
[PostgreSQL runbook](stage4d-postgres.md) for schema/loader commands. Installing
the optional driver does not install a server.

## Limits

Raw/interim/processed data, artifacts, configuration, environments and caches stay
ignored. Own code/docs use MIT; external MoMTSim has separate CC BY 4.0 licensing.
Full-scale PostgreSQL throughput, disk/WAL use, recovery and query plans remain
unmeasured. Exact entity/pair history grows with data size. Six synthetic days
cannot establish drift/seasonality generalisation. Enhanced pre-balance availability
is unproven in production. No API, dashboard, deployment, new features, additional
models or hyperparameter search was added during finalisation.
