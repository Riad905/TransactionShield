# Data policy

No dataset is included in the Git repository. Raw and generated data directories are ignored so that large files, derived artifacts, and external data cannot be committed accidentally.

The Stage 1 recommendation targets **dataset version 1 defined in the 2025 Data in Brief paper** ([DOI `10.1016/j.dib.2025.111534`](https://doi.org/10.1016/j.dib.2025.111534)): the smaller experimental dataset described by the authors. This content-level name is distinct from **Version 2 of the Mendeley Data repository** ([DOI `10.17632/zhj366m53p.2`](https://doi.org/10.17632/zhj366m53p.2)), which identifies the current repository release. Mendeley repository Version 2 must not be interpreted as automatically meaning the paper's larger dataset version 2.

The Stage 2 acquisition record includes:

- the source URL and dataset DOI;
- both version identifiers and the exact source filename;
- the download date;
- the CC BY 4.0 licence supplied by the Mendeley repository record; and
- any discrepancy from the published data article.

Stage 2 independently calculated from the selected downloaded file:

- row count;
- fraud count;
- legitimate count;
- fraud percentage;
- schema;
- file size; and
- cryptographic checksum.

The paper reports 1,720,181 rows, 175,518 fraud labels, 1,544,663 legitimate labels, and 10.20% fraud for its dataset version 1. These remain clearly labelled **publication values**. TransactionShield independently verified 1,720,181 rows, 175,518 fraud labels, 1,544,663 legitimate labels, and 10.203461% fraud in the acquired `synthetic_mobile_money_transaction_dataset.csv` file.

The external dataset is licensed separately under CC BY 4.0 and is not covered by TransactionShield's MIT License. The untouched source file is stored locally at `data/raw/synthetic_mobile_money_transaction_dataset.csv`; do not rename or edit it in place. Audit output is stored under `data/interim/`. `data/raw/`, `data/interim/`, and `data/processed/` remain local-only. See the [provenance record](../docs/data-provenance.md) for the authoritative URL, file identity, checksum, retrieval date, and acquisition decision.
