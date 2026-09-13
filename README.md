# TransactionShield — Leakage-Safe Fraud Modelling & Transaction Data Pipeline

TransactionShield is a Python portfolio project that validates **1,720,181 synthetic mobile-money transactions**, constructs leakage-safe historical features, implements atomic PostgreSQL persistence, and evaluates fixed fraud models chronologically. Exact Decimal arithmetic, checksum-verified replay and automated tests make the data path auditable. Models show only modest ranking gains; the six-day synthetic dataset cannot establish real-world fraud prevention.

The project includes **209 ordinary tests and five real PostgreSQL integration tests**. GitHub Actions runs the full suite against a disposable PostgreSQL service; local runs skip those five tests without a server. See [CI and reproduction](docs/portfolio-finalisation.md) for the observed verification status, not just workflow configuration.

## Modelling results: useful evidence, limited discrimination

The primary population is 569,328 synthetic TRANSFER transactions, with moderate class imbalance (30.83% fraud). Train/validation/test use steps 0-95 / 96-119 / 120-143, with no random split and no same-step history. Accuracy is not the headline metric: always predicting legitimate would achieve 70.63% test accuracy but detect no fraud, and false positives/negatives have asymmetric operational consequences.

The fixed experiments below use training-only preprocessing and validation-only threshold selection. Test prevalence is 29.37% across 99,093 examples. AP means Average Precision; precision/recall/F1 use each experiment's validation-selected threshold.

| Experiment | Validation AP | Test AP | Test ROC-AUC | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| Prevalence reference | 0.3066 | 0.2937 | 0.5000 | 0.2937 | 1.0000 | 0.4541 |
| Core Logistic Regression | 0.3482 | 0.3428 | 0.5462 | 0.3066 | 0.9988 | 0.4692 |
| Core histogram boosting | 0.3575 | 0.3533 | 0.5495 | 0.3088 | 0.9997 | 0.4718 |
| Enhanced Logistic Regression | 0.3490 | 0.3419 | 0.5464 | 0.3084 | 0.9957 | 0.4709 |
| Enhanced histogram boosting | 0.3578 | 0.3520 | 0.5479 | 0.3088 | 0.9995 | 0.4719 |

Enhanced boosting was selected by validation AP, before test evaluation. Its threshold **0.1806139476** maximises validation F1, not financial utility. On test it flags **95.05%** of transfers: **65,099 false positives, 15 false negatives, 29,089 true positives and 4,890 true negatives**. This is not an operationally useful alert policy. The prevalence-reference model flags everything at its validation-selected threshold; at 0.5 that baseline predicts everything legitimate.

At the predeclared 0.5 reference, Enhanced boosting has 97.01% precision but only 3.01% recall. This contrast shows why thresholds need an explicit cost/capacity objective, not just a default or a high F1. No test-based threshold retuning was performed.

Enhanced balances offered **no demonstrated improvement**: boosting test AP fell by 0.001323 versus Core, despite a tiny 0.000303 validation gain. Prior outgoing maximum amount was the largest positive validation permutation importance in both boosting models. These are associations, not causal effects; correlated features and synthetic rules limit interpretation.

### Fixed review budgets: concentrated top scores, low coverage

Descriptive post-hoc analysis of the frozen Enhanced model, with all five budgets predeclared:

| Review budget | Reviewed | Fraud captured | Precision | Recall | Lift |
|---|---:|---:|---:|---:|---:|
| 0.5% | 496 | 496 | 100.00% | 1.70% | 3.405 |
| 1% | 991 | 901 | 90.92% | 3.10% | 3.096 |
| 2% | 1,982 | 1,186 | 59.84% | 4.08% | 2.037 |
| 5% | 4,955 | 2,108 | 42.54% | 7.24% | 1.448 |
| 10% | 9,910 | 3,581 | 36.14% | 12.30% | 1.230 |

Review counts round up; tied scores retain replay order without consulting labels. Lift is precision divided by test prevalence. The tiny top slice is enriched, but reviewing 10% still misses 87.70% of fraud. No optimal budget, cost saving or real-world precision guarantee is claimed. A top-0.5% review budget is not a score threshold of 0.5. See [definitions, deterministic replay and reproduction](docs/portfolio-finalisation.md).

The six-day synthetic horizon cannot establish real-world fraud prevention, long-term drift robustness or financial benefit. Enhanced balance availability is also unproven. Full-data PostgreSQL loading remains **NOT RUN**; live fixture-test status is recorded in the [CI evidence](docs/portfolio-finalisation.md).

Reproduce after installing `.[dev,modelling]` and acquiring the approved ignored source:

```powershell
.\.venv\Scripts\python.exe -m transactionshield.modelling --source data/raw/synthetic_mobile_money_transaction_dataset.csv --output artifacts/stage4e-reproduction
```

See [experiment design and error analysis](docs/stage4e-modelling.md) and [exact aggregate results](docs/stage4e-results.json). No raw IDs, prediction dumps or fitted-model binaries are committed.

## Implementation history and current scope

Stage 1 established the project contract and repository conventions. Stage 2 acquired and audited the canonical artifact. Stage 3 froze these design contracts:

- a frozen lossless canonical PostgreSQL schema design derived from verified source representation;
- the transfer-only scoring-population contract;
- core and platform-state feature tiers with explicit forbidden inputs;
- a same-step-safe point-in-time history design;
- a reproducible per-step transfer summary and frozen temporal evaluation contract; and
- lightweight, tested eligibility, lineage-identity, representation, and summary utilities.

Stage 4B implements strict, streaming canonical ingestion, artifact verification before and during processing, lossless typed records, deterministic CSV materialisation, read-back reconciliation, and completed-run manifests. All transaction types, source labels, and post-balances are retained for canonical reconciliation; this output is not a model feature dataset. The earlier inspection utilities remain available and retain their documented behaviour.

Stage 4C implements the nine approved Core features and the separate two-field Platform-State Enhanced extension through a strict unlabelled behavioural interface. A two-phase replay isolates every current step from committed historical state. Source amounts and historical totals remain exact Decimal values; historical means use an explicit local 28-significant-digit HALF_EVEN context. All transaction types update history, but only transfers emit examples. Adversarial tests and streaming full-artifact validation check correctness without publishing a feature dataset.

Stage 4D adds explicit PostgreSQL migrations and a batched loader with source validation, read-back checks and atomic completion. Core predictors, Enhanced balances and feature metadata are stored separately. Psycopg is installed in the project environment, but **live PostgreSQL integration and full-data database loading have NOT RUN** because no local server or Docker environment was available. This is not a deployed database.

Stage 4E fits the five predeclared experiments above from verified in-memory features. Finalisation adds fixed-budget descriptive ranking analysis and PostgreSQL CI. The authoritative raw CSV and transaction-level generated outputs remain in Git-ignored local directories. No final feature-file format, saved model-serving bundle, API, dashboard, local Docker environment or cloud deployment is implemented. Synchronous pre-balance availability remains an unproven deployment assumption for the Enhanced tier.

The verified primary artifact is `synthetic_mobile_money_transaction_dataset.csv` from **Version 2 of the Mendeley Data repository**, DOI [`10.17632/zhj366m53p.2`](https://doi.org/10.17632/zhj366m53p.2). Its independently calculated row, class, transaction-type, and schema results identify it as **dataset version 1 defined by the 2025 Data in Brief paper**. These are separate version concepts. See [the original paper](https://doi.org/10.1016/j.dib.2025.111534), [provenance record](docs/data-provenance.md), and [dataset decision](docs/dataset-decision.md).

## Repository layout

```text
TransactionShield/
|-- data/                         # Local data policy; raw/generated data are ignored
|-- docs/
|   |-- architecture.md          # Current local pipeline and planned system
|   |-- canonical-data-model.md  # Verified representation and approved SQL types
|   |-- data-dictionary.md       # Verified schema, meanings, and availability
|   |-- data-provenance.md       # Source, acquisition, checksum, and identity
|   |-- data-quality-audit.md    # Integrity and quality findings
|   |-- dataset-decision.md      # Dataset evidence, comparison, and recommendation
|   |-- leakage-audit.md         # Feature disposition and temporal safeguards
|   |-- model-contract.md        # Population, feature tiers, and leakage rules
|   |-- project-specification.md # Business problem, metrics, and scope
|   |-- stage4b-canonical-pipeline.md # Canonical runbook and format contract
|   |-- stage4c-feature-engine.md # Point-in-time mechanism and validation runbook
|   |-- stage4d-postgres.md       # Persistence design and unexecuted live-test runbook
|   |-- stage4e-modelling.md      # Frozen experiment and honest limitations
|   |-- stage4e-results.json      # Lightweight aggregate metrics, no raw rows
|   |-- portfolio-finalisation.md # Ranking, replay evidence and CI/reproduction
|   |-- temporal-evaluation-contract.md # Stability, split, and metrics
|   `-- transfer-step-summary.csv        # Reproducible eligible-population counts
|-- sql/
|   |-- canonical_schema.sql     # Unchanged canonical design / first migration
|   `-- 002_persistence.sql      # Feature tables, constraints and views
|-- src/transactionshield/
|   |-- __init__.py
|   |-- audit.py                 # Streaming integrity and quality audit
|   |-- canonical.py             # Strict typed canonical parsing
|   |-- contracts.py             # Stage 3 contract inspection and rules
|   |-- features.py              # Narrow event boundary and two-phase history replay
|   |-- feature_validation.py    # Structural acceptance summaries; no feature files
|   |-- ingestion.py             # Compatible permissive inspection utilities
|   |-- materialisation.py       # Deterministic serialisation and read-back
|   |-- model_data.py            # Verified feature gate and estimator-only float boundary
|   |-- modelling.py             # Fixed chronological experiments and reports
|   |-- pipeline.py              # Canonical orchestration and CLI
|   |-- postgres.py              # Atomic batched persistence and read-back
|   `-- validation.py            # Approved artifact gate and reconciliation
|-- tests/
|   |-- conftest.py
|   |-- test_audit.py
|   |-- test_canonical.py
|   |-- test_contracts.py
|   |-- test_features.py
|   |-- test_feature_validation.py
|   |-- test_ingestion.py
|   |-- test_modelling.py
|   |-- test_pipeline.py
|   |-- test_postgres.py
|   |-- test_postgres_integration.py # Explicitly skipped without a test server
|   `-- test_ranking.py           # Fixed-capacity metrics and edge cases
|-- .github/workflows/ci.yml     # Ubuntu + genuine PostgreSQL service tests
|-- .gitignore
|-- LICENSE
|-- pyproject.toml
`-- README.md
```

## Development setup

Python 3.11 or newer is required. On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,postgres,modelling]"
python -m pytest
```

The file pipelines and feature engine use the Python standard library. The optional `modelling` extra pins sklearn and its numerical dependencies; reproduce the recorded experiment with Python 3.12.8. PostgreSQL access alone requires the optional `postgres` extra (Psycopg 3). Installing the driver does not install a server. Run only ordinary tests with `python -m pytest -m "not postgres"`. CI uses Python 3.12 on Ubuntu and requires all five database tests to execute without skips.

## Run the canonical pipeline

After the development setup above and the documented source acquisition:

```powershell
python -m transactionshield.pipeline data/raw/synthetic_mobile_money_transaction_dataset.csv `
  --output-directory data/interim/canonical/stage4b
```

The equivalent installed command is `transactionshield-canonical`. The output directory must be new and beneath `data/interim/` or `data/processed/`. A successful run contains `canonical.csv` and `manifest.json`; existing runs are never overwritten. See the [Stage 4B runbook](docs/stage4b-canonical-pipeline.md) for integrity gates, exact serialisation, failures, and deterministic reruns.

## Validate point-in-time features without materialising them

```powershell
python -m transactionshield.feature_validation data/raw/synthetic_mobile_money_transaction_dataset.csv `
  --report-output data/interim/stage4c-validation.json
```

This writes only a small structural acceptance summary to a new ignored report file. Feature examples are consumed and discarded; labels are not analysed for model performance. See the [Stage 4C runbook](docs/stage4c-feature-engine.md) for boundaries, cold starts, exact arithmetic and repeat verification.

## PostgreSQL persistence status

For Stage 4D setup, schema/load commands and opt-in real-database tests, see the
[PostgreSQL runbook](docs/stage4d-postgres.md). Only the Python driver was installed;
no database server was installed, and skipped integration tests are not counted as passes.

## Stage 1 environment snapshot

Checked on 5 September 2026:

| Tool | Result |
|---|---|
| Python | 3.12.8 |
| pip | 26.0 for Python 3.12 |
| `venv` | Available in the Python standard library |
| pytest | 9.0.2 already available in the inspected environment |
| Git | 2.53.0.windows.2 |
| Docker | Not detected on `PATH` or in the standard Docker Desktop location |
| PostgreSQL client | `psql` not detected on `PATH`; no standard installation folder detected |
| VS Code | 1.115.0, x64 |

Missing tools were not installed during Stage 1.

## Licensing

TransactionShield's own source code and original project documentation are available under the [MIT License](LICENSE). The external MoMTSim dataset is not part of this repository, is not covered by the TransactionShield MIT License, and is published under its own **CC BY 4.0** licence according to the [Mendeley Data repository Version 2 record](https://doi.org/10.17632/zhj366m53p.2). Raw external data remains excluded from Git. The verified source URL and integrity values are recorded in the provenance documentation.

## Documentation

- [Project specification](docs/project-specification.md)
- [Dataset decision](docs/dataset-decision.md)
- [Architecture](docs/architecture.md)
- [Canonical data model](docs/canonical-data-model.md)
- [Stage 4B canonical pipeline](docs/stage4b-canonical-pipeline.md)
- [Stage 4C point-in-time feature engine](docs/stage4c-feature-engine.md)
- [Data provenance and acquisition](docs/data-provenance.md)
- [Verified data dictionary](docs/data-dictionary.md)
- [Data-quality audit](docs/data-quality-audit.md)
- [Leakage and feature-availability audit](docs/leakage-audit.md)
- [Scoring and feature contract](docs/model-contract.md)
- [Temporal evaluation contract](docs/temporal-evaluation-contract.md)
- [Local data policy](data/README.md)
