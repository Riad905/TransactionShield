# TransactionShield

TransactionShield is a portfolio project for building an explainable, production-style transaction risk decisioning system. It is deliberately structured as a software and data product rather than as a single fraud-classification notebook.

## Current status: Stage 2 acquisition and audit only

Stage 1 established the project contract and repository conventions. Stage 2 adds:

- a provenance record for the authoritative Mendeley repository Version 2 artifact;
- an independently verified checksum, schema, row/class/type counts, and quality statistics;
- a streaming, dependency-free audit utility with focused tests;
- a column-level data dictionary and feature-availability assessment; and
- documented quality, leakage, temporal, and entity-feasibility findings.

The executable scope is limited to CSV header/row-shape validation, lazy string-row iteration, and the streaming audit utility. An authoritative raw CSV exists only in the Git-ignored local `data/raw/` directory and is not part of the repository. There is no typed production pipeline, trained model, database, API, dashboard, Docker configuration, CI workflow, or cloud infrastructure.

The verified primary artifact is `synthetic_mobile_money_transaction_dataset.csv` from **Version 2 of the Mendeley Data repository**, DOI [`10.17632/zhj366m53p.2`](https://doi.org/10.17632/zhj366m53p.2). Its independently calculated row, class, transaction-type, and schema results identify it as **dataset version 1 defined by the 2025 Data in Brief paper**. These are separate version concepts. See [the original paper](https://doi.org/10.1016/j.dib.2025.111534), [provenance record](docs/data-provenance.md), and [dataset decision](docs/dataset-decision.md).

## Repository layout

```text
TransactionShield/
|-- data/                         # Local data policy; raw/generated data are ignored
|-- docs/
|   |-- architecture.md          # Planned system and Stage 1 boundary
|   |-- data-dictionary.md       # Verified schema, meanings, and availability
|   |-- data-provenance.md       # Source, acquisition, checksum, and identity
|   |-- data-quality-audit.md    # Integrity and quality findings
|   |-- dataset-decision.md      # Dataset evidence, comparison, and recommendation
|   |-- leakage-audit.md         # Feature disposition and temporal safeguards
|   `-- project-specification.md # Business problem, metrics, and scope
|-- src/transactionshield/
|   |-- __init__.py
|   |-- audit.py                 # Streaming integrity and quality audit
|   `-- ingestion.py             # Header validation and lazy CSV row iteration
|-- tests/
|   |-- test_audit.py
|   `-- test_ingestion.py
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

The Stage 1 and Stage 2 code uses only the Python standard library. `pytest` is a development dependency used by the test suite.

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
- [Data provenance and acquisition](docs/data-provenance.md)
- [Verified data dictionary](docs/data-dictionary.md)
- [Data-quality audit](docs/data-quality-audit.md)
- [Leakage and feature-availability audit](docs/leakage-audit.md)
- [Local data policy](data/README.md)
