# Canonical data model

## Status and source contract

This is the approved Stage 3 PostgreSQL schema design, not an installed or executed database. The canonical source is the checksum-verified `synthetic_mobile_money_transaction_dataset.csv` from Mendeley repository Version 2. Its SHA-256 is `da951eb95735da96271740a3e66b676b342d3831ce3111cd19dbfa020d3bd0a7`.

The observed artifact is the source of truth: 1,720,181 rows and steps 0 through 143. The paper's separate 720-step configuration remains a documented limitation. All five transaction types and all source values, including negative balances and post-event fields, are retained in the canonical data layer.

The Stage 3 characteristics and transfer-step report are reproducible without loading the CSV into memory:

```powershell
python -m transactionshield.contracts data/raw/synthetic_mobile_money_transaction_dataset.csv `
  --report-output data/interim/stage3-contract-report.json `
  --step-output docs/transfer-step-summary.csv
```

## Verified numeric representation

Integer digits count digits to the left of the decimal point after removing the sign and non-significant leading zeros; zero counts as one digit. Decimal places count the literal digits present after the decimal point.

| Source column | Minimum | Maximum | Maximum integer digits | Maximum decimal places |
|---|---:|---:|---:|---:|
| `amount` | 0.24 | 2,142,928.28 | 7 | 2 |
| `oldBalInitiator` | -199,997.11 | 12,244,691.62 | 8 | 2 |
| `newBalInitiator` | -199,997.11 | 12,244,691.62 | 8 | 2 |
| `oldBalRecipient` | -198,368.47 | 11,885,539.37 | 8 | 2 |
| `newBalRecipient` | -135,727.98 | 12,066,212.12 | 8 | 2 |

PostgreSQL `NUMERIC` without a declared precision or scale is approved for all five fields. It stores the observed decimal values exactly while avoiding a sample-maximum constraint that could reject a valid future source revision. `amount > 0` is the approved numeric domain check: every verified amount is positive and the field represents a transaction amount. Balances deliberately have no non-negative check because verified negative values must be preserved.

## Verified identifier representation

The counts below are source-row occurrences; Stage 2 separately records exact unique entity cardinalities.

| Column | Observed formats | Row occurrences | Lengths | Maximum length |
|---|---|---:|---|---:|
| `initiator` | Numeric digits only | 1,720,181 | 16 | 16 |
| `recipient` | Numeric digits only | 569,328 | 16 | 16 |
| `recipient` | `NN-NNNNNNN` | 1,142,179 | 10 | 16 overall |
| `recipient` | `LNN-NNNNNNN` | 5,392 | 11 | 16 overall |
| `recipient` | `NN-NNNNNNN-NNNN` | 3,282 | 15 | 16 overall |

Both IDs use PostgreSQL `TEXT`. Although every initiator in this artifact is a 16-digit string, it is an opaque identifier, not a quantity. `TEXT` preserves lexical identity, supports all recipient formats, avoids accidental arithmetic, and does not freeze sample-specific lengths. Only non-empty checks are approved. Raw IDs remain join keys for point-in-time history and are not direct model inputs.

## Table design and source mapping

The approved, unexecuted DDL is in [`sql/canonical_schema.sql`](../sql/canonical_schema.sql).

| Source | Canonical column | PostgreSQL type | Constraint rationale |
|---|---|---|---|
| Load contract | `transaction_id` | `UUID` | Deterministic technical lineage identity; primary key |
| Load contract | `artifact_id` | `UUID` | Links each row to immutable artifact metadata |
| CSV logical record | `source_row_number` | `BIGINT` | Starts at 2 because the header is record 1; unique within artifact |
| `step` | `step` | `INTEGER` | Non-negative; no upper bound tied to this sample |
| `transactionType` | `transaction_type` | `TEXT` | Restricted to the five paper- and artifact-verified values |
| `amount` | `amount` | `NUMERIC` | Exact decimal; positive domain |
| `initiator` | `initiator_id` | `TEXT` | Opaque non-empty identifier |
| `oldBalInitiator` | `initiator_balance_before` | `NUMERIC` | Exact decimal; negative values allowed |
| `newBalInitiator` | `initiator_balance_after` | `NUMERIC` | Preserved for reconciliation; forbidden for prediction |
| `recipient` | `recipient_id` | `TEXT` | Opaque mixed-format non-empty identifier |
| `oldBalRecipient` | `recipient_balance_before` | `NUMERIC` | Exact decimal; negative values allowed |
| `newBalRecipient` | `recipient_balance_after` | `NUMERIC` | Preserved for reconciliation; forbidden for prediction |
| `isFraud` | `is_fraud` | `SMALLINT` | Exact source domain `{0, 1}`; target only |

## Deterministic identity contract

`transaction_id` is computed by the ingestion application, not by row insertion order:

```text
namespace = e42d9db1-0152-5973-b3b0-6df189dc50e4
name      = lower-case artifact SHA-256 + ":" + source_row_number
id        = UUIDv5(namespace, name)
```

The namespace is `UUIDv5(UUID_NAMESPACE_URL, "https://github.com/Riad905/TransactionShield")`. For the canonical artifact and source row 2, the transaction ID is `9a10d98b-85ee-5bbb-bbc5-ed4148483b9b`. Re-loading the same artifact produces the same identities. Neither `transaction_id` nor `source_row_number` establishes event order inside a step; `step` is the only verified temporal field and same-step ordering is unavailable.

The dataset-level `artifact_id` is likewise stable for a checksum-identified artifact. Its canonical value, UUIDv5 of the SHA-256 under the same namespace, is `3de76748-4701-53f9-8ddf-ccaf6615d63a`.

## Approved ingestion failure behaviour

The future ingestion layer must validate source values before inserting canonical rows. Invalid plain-decimal values, non-positive amounts, empty IDs, unexpected transaction types or labels, invalid steps, and deterministic-identity conflicts must be rejected and reported with source-row and column context. It must not trim malformed identifiers into validity, clip or replace negative balances, round source decimals, substitute defaults, or silently discard invalid rows. A failed canonical load must leave an auditable failure result rather than a partially accepted dataset presented as complete.
