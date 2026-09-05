# Leakage and feature-availability audit

## Decision moment

TransactionShield's intended prediction moment is before a transaction is completed and before any action is taken from the model score. A feature is eligible only if the scoring system could know it at that moment. Synthetic availability does not prove real serving availability.

## Column disposition

### Availability-safe input and temporal context

- `amount`: supplied with the transaction. Its simulator relationship to fraud still needs distribution and ablation checks.
- `step`: known simulation event time and safe for temporal partitioning and point-in-time joins. Stage 3 excludes its absolute value as a direct MVP model feature because it has no portable production meaning.

“Safe” here means plausibly available before the decision, not proven free of simulator artefacts.

### Requires point-in-time transformation

- `initiator`
- `recipient`

These identifiers support velocity, prior-count, prior-amount, counterparty, and network features, but those features must use only events with `historical_step < current_step`. The one-hour `step` granularity does not establish a reliable order within the same step, so same-step rows must not be treated as prior history without further source evidence. Raw identifiers should not be passed directly to a model by default because they can memorise simulated entities.

### Exclude from the predictive model

- `newBalInitiator`: post-transaction state.
- `newBalRecipient`: post-transaction state.
- `isFraud`: target/outcome label.

The new-balance fields may remain available for post-event data-quality reconciliation, but not for pre-transaction training or inference.

### Requires further investigation

- `transactionType`: operationally available, but all 175,518 fraud rows are `TRANSFER`; the other four types contain zero fraud.
- `oldBalInitiator`: described as pre-transaction state, but negative balances and simulator behaviours require investigation before use.
- `oldBalRecipient`: described as pre-transaction state, but a real scoring service may need a separate state lookup; negative values and serving availability require investigation.

## Empirical leakage signals

### Transaction-type shortcut

Every fraud label occurs in `TRANSFER`. Transfers have 175,518 fraud rows out of 569,328 (30.828977%); every `DEBIT`, `DEPOSIT`, `PAYMENT`, and `WITHDRAWAL` row is labelled legitimate. Transaction type is not the target itself and is plausibly known at decision time, but this concentration may reflect simulator design rather than a transferable fraud relationship.

Controls for later modelling:

- report performance by transaction type;
- compare models with and without `transactionType`;
- never claim detection coverage for types with no positive examples; and
- use the Stage 3 primary population contract, which scores transfers only while preserving all transaction types in the data layer.

### Post-balance arithmetic

All 175,518 fraud rows fall in the “combined initiator/recipient balance conserved” pattern. No fraud row appears in the 483,094 rows classified as a non-conserved combined balance update. Because this pattern requires `newBalInitiator` and `newBalRecipient`, it is a post-transaction shortcut and is excluded.

Observed fraud rates by balance-update pattern further show label association:

| Pattern | Fraud / total | Fraud rate |
|---|---:|---:|
| Combined balances conserved | 175,518 / 1,237,087 | 14.188008% |
| Combined balances other | 0 / 483,094 | 0% |
| Initiator decreases by amount | 145,475 / 1,132,047 | 12.850615% |
| Initiator unchanged | 11,407 / 52,821 | 21.595578% |
| Recipient increases by amount | 151,545 / 1,067,969 | 14.190019% |
| Recipient unchanged | 11,407 / 535,915 | 2.128509% |

These associations do not establish causality, but they make post-balance exclusion non-negotiable and justify later ablations of pre-balance fields.

### Entity identifiers

No initiator or recipient appears only in fraud rows. Initiators comprise 3,176 legitimate-only IDs and 10,286 mixed-label IDs; recipients comprise 11,731 legitimate-only IDs and 5,000 mixed-label IDs. This rules out a simple “fraud-only ID” shortcut in the observed file, but random row splits could still let a model memorise entity-specific risk from future observations.

Controls:

- split by whole chronological step ranges;
- compute histories from earlier steps only;
- evaluate sensitivity to unseen or low-history entities; and
- do not encode raw IDs as ordinary categorical features without a documented experiment and justification.

### Negative balances

Rows with at least one negative balance contain 6,170 fraud and 42,043 legitimate labels, a 12.797% fraud rate versus 10.203461% overall. This difference warrants investigation but is not evidence that negative balances directly encode fraud. Post-transaction negative balances remain excluded with the other new-balance fields.

## Stage 2 temporal split feasibility

The file is sorted non-decreasingly across 144 complete step values from 0 to 143. Fraud occurs in every step. A feasibility-only split on whole steps produces:

| Window | Step range | Rows | Fraud | Fraud rate |
|---|---:|---:|---:|---:|
| First 60% feasibility window | 0–85 | 1,106,698 | 105,266 | 9.511719% |
| Next 20% feasibility window | 86–114 | 254,762 | 35,200 | 13.816817% |
| Final 20% feasibility window | 115–143 | 358,721 | 35,052 | 9.771382% |

This Stage 2 full-dataset calculation demonstrated that non-overlapping chronological windows are technically possible and that prevalence changes over time. It is superseded for primary modelling by the frozen transfer-only Stage 3 split: train 0–95, validation 96–119, and test 120–143. The 144-step file horizon represents only six synthetic days, conflicts with the paper's reported 720-step configuration, and cannot demonstrate long-term seasonality or drift generalisation.

## Entity history and graph feasibility

- 11,913 initiators and 14,374 recipients occur at multiple steps, so point-in-time account-history features are technically feasible.
- 6,174 identifiers occur in both initiator and recipient roles.
- Each row supplies a directed initiator-to-recipient relationship, so later transaction-network analysis is technically possible.
- Recipient IDs use mixed textual formats, but the source does not document enough business semantics to infer entity types from those formats.
- Graph construction, graph features, and graph models remain later work; none were built in Stage 2.
