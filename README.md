# TransactionShield

TransactionShield is a portfolio project for building an explainable, production-style transaction risk decisioning system. It is deliberately structured as a software and data product rather than as a single fraud-classification notebook.

## Current status: Stage 1 foundation only

Stage 1 establishes the project contract and repository conventions. It contains:

- a documented business problem, MVP boundary, and later extensions;
- an evidence-based comparison of MoMTSim, PaySim, and IEEE-CIS;
- a planned architecture whose future components are clearly marked;
- a small, dependency-free CSV schema inspection and row-iteration interface; and
- tests for that interface.

The only executable project functionality currently implemented is CSV header/row-shape validation and lazy string-row iteration. The repository does **not** contain a downloaded dataset, typed data pipeline, trained model, database, API, dashboard, Docker configuration, CI workflow, or cloud infrastructure.

The recommended target is **dataset version 1 as defined by the 2025 Data in Brief paper**: the paper's smaller experimental dataset. This is distinct from **Version 2 of the Mendeley Data repository**, DOI [`10.17632/zhj366m53p.2`](https://doi.org/10.17632/zhj366m53p.2), which is the current repository release rather than the paper's larger “dataset version 2.” The exact source file will not be treated as validated until Stage 2 independently calculates its schema, counts, percentage, size, and checksum. See [the original paper](https://doi.org/10.1016/j.dib.2025.111534) and [the dataset decision](docs/dataset-decision.md).

## Repository layout

```text
TransactionShield/
|-- data/                         # Local data policy; raw/generated data are ignored
|-- docs/
|   |-- architecture.md          # Planned system and Stage 1 boundary
|   |-- dataset-decision.md      # Dataset evidence, comparison, and recommendation
|   `-- project-specification.md # Business problem, metrics, and scope
|-- src/transactionshield/
|   |-- __init__.py
|   `-- ingestion.py             # Header validation and lazy CSV row iteration only
|-- tests/
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

The Stage 1 implementation itself uses only the Python standard library. `pytest` is a development dependency used by the test suite.

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

TransactionShield's own source code and original project documentation are available under the [MIT License](LICENSE). The external MoMTSim dataset is not part of this repository, is not covered by the TransactionShield MIT License, and is published under its own **CC BY 4.0** licence according to the [Mendeley Data repository Version 2 record](https://doi.org/10.17632/zhj366m53p.2). Raw external data remains excluded from Git; reproducible acquisition instructions will be added after the exact source file is validated.

## Documentation

- [Project specification](docs/project-specification.md)
- [Dataset decision](docs/dataset-decision.md)
- [Architecture](docs/architecture.md)
- [Local data policy](data/README.md)
