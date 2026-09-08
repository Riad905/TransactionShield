# TransactionShield

TransactionShield is a portfolio project for building an explainable, production-style transaction risk decisioning system. It is deliberately structured as a software and data product rather than as a single fraud-classification notebook.

## Current status: Stage 4C point-in-time feature engine

Stage 1 established the project contract and repository conventions. Stage 2 acquired and audited the canonical artifact. Stage 3 froze these design contracts:

- a frozen lossless canonical PostgreSQL schema design derived from verified source representation;
- the transfer-only scoring-population contract;
- core and platform-state feature tiers with explicit forbidden inputs;
- a same-step-safe point-in-time history design;
- a reproducible per-step transfer summary and frozen temporal evaluation contract; and
- lightweight, tested eligibility, lineage-identity, representation, and summary utilities.

Stage 4B implements strict, streaming canonical ingestion, artifact verification before and during processing, lossless typed records, deterministic CSV materialisation, read-back reconciliation, and completed-run manifests. All transaction types, source labels, and post-balances are retained for canonical reconciliation; this output is not a model feature dataset. The earlier inspection utilities remain available and retain their documented behaviour.

Stage 4C implements the nine approved Core features and the separate two-field Platform-State Enhanced extension through a strict unlabelled behavioural interface. A two-phase replay isolates every current step from committed historical state. Source amounts and historical totals remain exact Decimal values; historical means use an explicit local 28-significant-digit HALF_EVEN context. All transaction types update history, but only transfers emit examples. Adversarial tests and streaming full-artifact validation check correctness without publishing a feature dataset.

The PostgreSQL file remains unexecuted design DDL. The authoritative raw CSV and transaction-level generated outputs exist only in Git-ignored local data directories. No PostgreSQL integration (4D), final feature materialisation (4E), fitted model, API, dashboard, Docker configuration, CI workflow, or cloud infrastructure have been implemented. Synchronous pre-balance availability remains an unproven deployment assumption for the Enhanced tier.

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
|   |-- temporal-evaluation-contract.md # Stability, split, and metrics
|   `-- transfer-step-summary.csv        # Reproducible eligible-population counts
|-- sql/
|   `-- canonical_schema.sql     # Approved design; not executed
|-- src/transactionshield/
|   |-- __init__.py
|   |-- audit.py                 # Streaming integrity and quality audit
|   |-- canonical.py             # Strict typed canonical parsing
|   |-- contracts.py             # Stage 3 contract inspection and rules
|   |-- features.py              # Narrow event boundary and two-phase history replay
|   |-- feature_validation.py    # Structural acceptance summaries; no feature files
|   |-- ingestion.py             # Compatible permissive inspection utilities
|   |-- materialisation.py       # Deterministic serialisation and read-back
|   |-- pipeline.py              # Canonical orchestration and CLI
|   `-- validation.py            # Approved artifact gate and reconciliation
|-- tests/
|   |-- test_audit.py
|   |-- test_canonical.py
|   |-- test_contracts.py
|   |-- test_features.py
|   |-- test_feature_validation.py
|   |-- test_ingestion.py
|   `-- test_pipeline.py
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
python -m pip install -e ".[dev]"
python -m pytest
```

The code implemented through Stage 4C uses only the Python standard library. `pytest` is a development dependency used by the test suite.

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
