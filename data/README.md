# Data policy

No dataset is included in the repository. Raw and generated data directories are ignored by Git so that large files, derived artifacts, and external data cannot be committed accidentally.

The Stage 1 recommendation targets **dataset version 1 defined in the 2025 Data in Brief paper** ([DOI `10.1016/j.dib.2025.111534`](https://doi.org/10.1016/j.dib.2025.111534)): the smaller experimental dataset described by the authors. This content-level name is distinct from **Version 2 of the Mendeley Data repository** ([DOI `10.17632/zhj366m53p.2`](https://doi.org/10.17632/zhj366m53p.2)), which identifies the current repository release. Mendeley repository Version 2 must not be interpreted as automatically meaning the paper's larger dataset version 2.

Before Stage 2 analysis, acquisition must record:

- the source URL and dataset DOI;
- both version identifiers and the exact source filename;
- the download date;
- the CC BY 4.0 licence supplied by the Mendeley repository record; and
- any discrepancy from the published data article.

Stage 2 will independently calculate from the selected downloaded file:

- row count;
- fraud count;
- legitimate count;
- fraud percentage;
- schema;
- file size; and
- cryptographic checksum.

The paper reports 1,720,181 rows, 175,518 fraud labels, 1,544,663 legitimate labels, and 10.20% fraud for its dataset version 1. These are authoritative **publication values used as acquisition checks**, not locally verified characteristics of an exact repository file. Stage 1 intentionally does not download or inspect any dataset file.

The external dataset is licensed separately under CC BY 4.0 and is not covered by TransactionShield's MIT License. When acquisition is approved, place the untouched source file under `data/raw/`. Do not rename or edit it in place. Later pipeline outputs should go under `data/interim/` or `data/processed/`; all three paths remain local-only. The repository should contain reproducible acquisition instructions and provenance metadata, not the raw dataset.
