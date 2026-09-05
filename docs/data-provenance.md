# Data provenance and acquisition record

## Pre-download repository snapshot

- **Recorded on:** 5 September 2026
- **Repository:** Mendeley Data, *Synthetic Mobile Money Transaction Dataset*
- **Contributor:** Denish Azamuke
- **Repository release:** Version 2, published 29 October 2024
- **Repository DOI:** [`10.17632/zhj366m53p.2`](https://doi.org/10.17632/zhj366m53p.2)
- **Authoritative source page:** <https://data.mendeley.com/datasets/zhj366m53p/2>
- **Authoritative public file API:** <https://data.mendeley.com/public-api/datasets/zhj366m53p/files?folder_id=root&version=2>
- **Repository licence:** [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/)

The Mendeley repository Version 2 page listed these files before acquisition:

| Repository filename | Mendeley-displayed size | API-reported bytes | Repository-provided SHA-256 | Acquisition order |
|---|---:|---:|---|---|
| `synthetic_mobile_money_transaction_dataset.csv` | approximately 149 MB | 156,564,413 | `da951eb95735da96271740a3e66b676b342d3831ce3111cd19dbfa020d3bd0a7` | First: smaller candidate |
| `MoMTSim_20240722202413_1000_dataset.csv` | approximately 349 MB | 366,397,921 | `99fd07c3a9d3c4bd6d3462240058ca19d0d9e9284683f78bf77542ff7fcc05e7` | Only if the first candidate is not the intended paper-defined dataset version 1 |

The displayed sizes are rounded for presentation. The byte counts and digests in this table are metadata returned by Mendeley's public file API before download. The selected file's values were then verified locally, as recorded below.

## Separate publication expectations

The 2025 *Data in Brief* article, [“A labeled synthetic mobile money transaction dataset”](https://doi.org/10.1016/j.dib.2025.111534), separately defines two dataset variants:

| Paper-defined dataset variant | Paper-reported rows | Paper-reported class distribution |
|---|---:|---|
| Dataset version 1 | 1,720,181 | 1,544,663 legitimate (89.80%); 175,518 fraud (10.20%) |
| Dataset version 2 | 4,225,958 | 1,992,840 legitimate (47.16%); 2,233,118 fraud (52.84%) |

The paper's dataset-version labels and Mendeley's repository-version label are independent. Filename and displayed size are not accepted as proof that a repository file corresponds to a paper-defined variant.

## Acquisition plan

1. Download only `synthetic_mobile_money_transaction_dataset.csv` from the authoritative Mendeley record.
2. Preserve it unchanged under the Git-ignored `data/raw/` directory.
3. Record its exact byte size and SHA-256 digest.
4. Stream the CSV to calculate its schema, row/class/type counts, malformed rows, and quality statistics.
5. Compare calculated values with the paper; do not repair discrepancies silently.
6. Download the larger candidate only if the smaller artifact does not empirically match the paper-defined dataset version 1.

## Acquisition result

Acquisition completed on 5 September 2026 using the smaller candidate only.

| Property | Independently verified value |
|---|---|
| Exact filename | `synthetic_mobile_money_transaction_dataset.csv` |
| Mendeley file ID | `57c2ed32-a9b6-4af8-9510-9b064625d5d7` |
| Authoritative download URL | `https://data.mendeley.com/public-files/datasets/zhj366m53p/files/57c2ed32-a9b6-4af8-9510-9b064625d5d7/file_downloaded` |
| Local raw path | `data/raw/synthetic_mobile_money_transaction_dataset.csv` (Git-ignored) |
| Byte size | 156,564,413 bytes |
| SHA-256 | `da951eb95735da96271740a3e66b676b342d3831ce3111cd19dbfa020d3bd0a7` |
| Encoding | UTF-8 without a byte-order mark |
| Header | `step,transactionType,amount,initiator,oldBalInitiator,newBalInitiator,recipient,oldBalRecipient,newBalRecipient,isFraud` |
| Data rows | 1,720,181 |
| Class counts | 1,544,663 legitimate; 175,518 fraud; 10.203461% fraud |

The local byte size and SHA-256 exactly match Mendeley's repository metadata. The row, class, transaction-type, and schema results match the paper-defined dataset version 1, so the larger repository file was not downloaded. The acquired file contains 144 distinct `step` values from 0 through 143, however, whereas the paper's configuration table reports 720 steps. This discrepancy remains documented and unresolved; no data was changed.

The raw CSV and generated machine-readable audit report remain local under ignored data directories. Reproduction and detailed findings are recorded in the [data-quality audit](data-quality-audit.md), [data dictionary](data-dictionary.md), and [leakage audit](leakage-audit.md).

## Reproduce the acquisition and integrity check

From the repository root on Windows PowerShell:

```powershell
New-Item -ItemType Directory -Force data/raw | Out-Null
Invoke-WebRequest `
  -Uri "https://data.mendeley.com/public-files/datasets/zhj366m53p/files/57c2ed32-a9b6-4af8-9510-9b064625d5d7/file_downloaded" `
  -OutFile "data/raw/synthetic_mobile_money_transaction_dataset.csv"
Get-FileHash -Algorithm SHA256 data/raw/synthetic_mobile_money_transaction_dataset.csv
python -m transactionshield.audit data/raw/synthetic_mobile_money_transaction_dataset.csv `
  --output data/interim/momtsim-repository-v2-smaller-file-audit.json `
  --work-directory data/interim
```

The download should be accepted only if its byte size and SHA-256 match the verified values above. These commands write only to Git-ignored data directories.
