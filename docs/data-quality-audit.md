# Data-quality audit

## Scope and method

TransactionShield audited the smaller candidate from [Mendeley Data repository Version 2](https://doi.org/10.17632/zhj366m53p.2) using the streaming `transactionshield.audit` module. The raw CSV was not loaded into a dataframe. Duplicate checking used SHA-256 fingerprints of canonical parsed rows in a temporary on-disk SQLite index; the temporary index was removed after the run.

The ignored machine-readable report can be reproduced locally with:

```powershell
python -m transactionshield.audit data/raw/synthetic_mobile_money_transaction_dataset.csv `
  --output data/interim/momtsim-repository-v2-smaller-file-audit.json `
  --work-directory data/interim
```

## Integrity and structure

| Check | Independently verified result |
|---|---|
| Filename | `synthetic_mobile_money_transaction_dataset.csv` |
| Byte size | 156,564,413 bytes |
| SHA-256 | `da951eb95735da96271740a3e66b676b342d3831ce3111cd19dbfa020d3bd0a7` |
| Encoding | UTF-8, no byte-order mark |
| Header | `step,transactionType,amount,initiator,oldBalInitiator,newBalInitiator,recipient,oldBalRecipient,newBalRecipient,isFraud` |
| Columns | 10 |
| Data rows | 1,720,181 |
| Valid-width rows | 1,720,181 |
| Malformed/wrong-width rows | 0 |
| Duplicate rows | 0 |
| Missing values | 0 in every column |

The local byte size and SHA-256 exactly match the metadata returned by Mendeley's public file API.

## Labels and transaction types

| Label | Independently verified count | Percentage |
|---|---:|---:|
| Legitimate (`0`) | 1,544,663 | 89.796539% |
| Fraud (`1`) | 175,518 | 10.203461% |
| **Total** | **1,720,181** | **100%** |

| Transaction type | Independently verified count | Percentage of rows | Fraud count |
|---|---:|---:|---:|
| `DEBIT` | 5,392 | 0.313455% | 0 |
| `DEPOSIT` | 384,431 | 22.348288% | 0 |
| `PAYMENT` | 667,245 | 38.789232% | 0 |
| `TRANSFER` | 569,328 | 33.096982% | 175,518 |
| `WITHDRAWAL` | 93,785 | 5.452043% | 0 |

The label domain is exactly `{0, 1}` and the transaction-type domain is exactly the five types described by the paper.

## Comparison with published values

| Property | Paper-defined dataset version 1 | TransactionShield verification | Result |
|---|---:|---:|---|
| Rows | 1,720,181 | 1,720,181 | Match |
| Legitimate | 1,544,663 | 1,544,663 | Match |
| Fraud | 175,518 | 175,518 | Match |
| Fraud percentage | 10.20% (rounded) | 10.203461% | Match at paper precision |
| Type counts | 384,431 deposit; 93,785 withdrawal; 569,328 transfer; 667,245 payment; 5,392 debit | Same counts | Match |
| Schema | Ten named fields | Same ten names and order | Match |
| Simulation steps | Configuration table reports 720 | 144 distinct values, range 0–143 | **Discrepancy** |

The exact row, label, type, and schema matches identify this artifact as the paper-defined dataset version 1. The step discrepancy is not silently corrected: the acquired file represents 144 hourly step values even though the paper reports a 720-step generation configuration. This requires clarification or an explicit limitation in later work.

## Amount, ordering, and domains

- Amount range: 0.24 to 2,142,928.28 simulator units.
- Non-positive amounts: 0.
- Invalid numeric values: 0.
- NaN or infinite numeric values: 0.
- Rows are non-decreasing by `step`; out-of-order transitions: 0.
- All step values from 0 through 143 are present.
- No field was constant or at least 99% dominated by one value.
- No source-supported upper amount limit was imposed, so the maximum is reported for review rather than called impossible.

## Entities and repeated history

| Check | Result |
|---|---:|
| Distinct initiators | 13,462 |
| Distinct recipients | 16,731 |
| IDs appearing in both roles | 6,174 |
| Initiators with multiple rows | 12,476 |
| Recipients with multiple rows | 14,423 |
| Initiators observed at multiple steps | 11,913 |
| Recipients observed at multiple steps | 14,374 |

## Balance findings requiring investigation

| Field | Negative-value rows |
|---|---:|
| `oldBalInitiator` | 44,402 |
| `newBalInitiator` | 44,621 |
| `oldBalRecipient` | 117 |
| `newBalRecipient` | 15 |

There are 48,213 rows with at least one negative balance (2.802786% of rows). Because fields can overlap, individual column counts do not sum to unique rows. The paper mentions overdraft constraints, so these values are not automatically classified as errors. Their distribution and simulator meaning need confirmation before feature use.

Balance-delta checks also found substantial `other` or unchanged outcomes rather than an exact amount movement:

| Type | Rows | Expected-direction initiator delta | Initiator `other` | Initiator unchanged | Expected-direction recipient delta | Recipient `other` | Recipient unchanged |
|---|---:|---:|---:|---:|---:|---:|---:|
| `DEBIT` | 5,392 | 4,601 decrease | 701 | 90 | n/a | 0 | 5,392 |
| `DEPOSIT` | 384,431 | 334,428 increase | 50,003 | 0 | n/a | 0 | 384,431 |
| `PAYMENT` | 667,245 | 562,637 decrease | 75,214 | 29,394 | 565,082 increase | 72,769 | 29,394 |
| `TRANSFER` | 569,328 | 483,331 decrease | 63,084 | 22,913 | 502,887 increase | 43,528 | 22,913 |
| `WITHDRAWAL` | 93,785 | 81,478 decrease | 11,883 | 424 | n/a | 0 | 93,785 |

These are arithmetic observations, not proof of corruption. Possible explanations include simulator overdraft, insufficient-funds, or actor-specific rules, but the dataset alone does not establish a cause. No cleaning or repair has been applied.
