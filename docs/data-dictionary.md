# Verified data dictionary

This dictionary describes the locally audited `synthetic_mobile_money_transaction_dataset.csv` artifact acquired from [Mendeley Data repository Version 2](https://doi.org/10.17632/zhj366m53p.2) on 5 September 2026. Semantic descriptions are limited to those supported by the [2025 Data in Brief paper](https://doi.org/10.1016/j.dib.2025.111534). Observed statistics were calculated by TransactionShield; they are not copied from the paper.

All 1,720,181 parsed data rows had exactly ten fields. Every column had zero nulls. For high-cardinality numeric columns, the streaming audit stopped retaining distinct values after 10,000; this bounds memory without implying an exact cardinality.

| Column | Observed type | Supported meaning | Null count/rate | Unique count | Example values | Apparent availability | Preliminary leakage risk |
|---|---|---|---:|---:|---|---|---|
| `step` | Integer | Simulation time unit; the paper maps one step to one hour. | 0 / 0% | 144 | `0`, `1`, `2` | Before/during decision | Low, but use chronological validation |
| `transactionType` | String | `DEPOSIT`, `WITHDRAWAL`, `TRANSFER`, `PAYMENT`, or `DEBIT`. | 0 / 0% | 5 | `TRANSFER`, `PAYMENT`, `DEPOSIT` | Before/during decision | Investigate: every observed fraud is a transfer |
| `amount` | Number | Transaction amount in the simulator's units. | 0 / 0% | >10,000 | `19824.96`, `598.97`, `545.85` | Before decision | Low availability risk; simulator-rule relationship still requires testing |
| `initiator` | Integer-like identifier | ID of the transaction initiator. Treat as an identifier, not a quantity. | 0 / 0% | 13,462 | `4537027967639631`, `4296267625767470`, `4178224023847746` | Before decision | Investigate: raw IDs can memorise simulated entities |
| `oldBalInitiator` | Number | Initiator balance before the transaction. | 0 / 0% | >10,000 | `187712.18`, `8.92`, `93.6` | Before decision if the serving system exposes current balance | Investigate: negative values and simulator state may encode behaviour |
| `newBalInitiator` | Number | Initiator balance after the transaction. | 0 / 0% | >10,000 | `167887.22`, `8.92`, `-452.25` | Only after transaction completion | High: post-outcome value; exclude from pre-transaction model |
| `recipient` | String identifier | ID of the transaction recipient. Values use more than one textual format. | 0 / 0% | 16,731 | `4875702729424478`, `25-0000401`, `13-0001587` | Before/during decision | Investigate: raw IDs can memorise simulated entities |
| `oldBalRecipient` | Number | Recipient balance before the transaction. | 0 / 0% | >10,000 | `8.31`, `0.0`, `4011.72` | During processing if recipient state is queryable | Investigate: availability contract and negative values need confirmation |
| `newBalRecipient` | Number | Recipient balance after the transaction. | 0 / 0% | >10,000 | `19833.27`, `0.0`, `545.85` | Only after transaction completion | High: post-outcome value; exclude from pre-transaction model |
| `isFraud` | Integer label | `1` for simulated fraud and `0` for a simulated legitimate transaction. | 0 / 0% | 2 | `1`, `0` | Outcome/ground truth only | High: target label; never a model input |

## Observed numeric ranges

| Column | Minimum | Maximum |
|---|---:|---:|
| `step` | 0 | 143 |
| `amount` | 0.24 | 2,142,928.28 |
| `oldBalInitiator` | -199,997.11 | 12,244,691.62 |
| `newBalInitiator` | -199,997.11 | 12,244,691.62 |
| `oldBalRecipient` | -198,368.47 | 11,885,539.37 |
| `newBalRecipient` | -135,727.98 | 12,066,212.12 |
| `isFraud` | 0 | 1 |

The audit found no invalid or non-finite numeric values. Negative balances are recorded as investigation findings rather than errors because the source paper describes simulator overdraft constraints but does not provide enough evidence here to classify every negative value as valid or invalid.
