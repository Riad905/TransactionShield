# Stage 4C: point-in-time feature engine

## Scope and frozen decisions

Implemented: a narrow unlabelled behavioural input, exact entity/counterparty
state, two-phase completed-step replay, nine Core features, a separate Enhanced
extension, and structural acceptance without persistent feature examples.

Only exact `TRANSFER` transactions emit primary examples. **All valid canonical
transactions update history**, including DEBIT, DEPOSIT, PAYMENT and WITHDRAWAL.
No source value, population, temporal split or existing feature definition was
changed. No PostgreSQL, model, API, graph infrastructure or final feature-file
materialisation is implemented. No runtime dependency was added.

## Boundaries and architecture

```text
Verified source bytes -> Stage 4B canonical parser -> canonical records
  -> explicit five-field BehaviouralEvent projection -> HistoryEngine -> CoreFeatures
  -> current pre-balances, outside history ---------------------------> EnhancedFeatures
  -> technical/source identity and step ------------------------------> FeatureLineage
```

`BehaviouralEvent` is a frozen slotted dataclass containing only `step`,
`transaction_type`, `amount`, `initiator_id`, and `recipient_id`. The engine
rejects canonical objects, richer duck-typed objects and subclasses rather than
accepting an interface that could accidentally carry labels or post-balances.

`CoreFeatures` has exactly nine predictor fields, no identifiers or step.
`EnhancedFeatures` contains the Core object and two current pre-balances.
`FeatureExample` separates these predictor objects from `FeatureLineage`.
Fraud targets remain outside this adapter; the canonical parser may validate
their source domain, but the feature engine and acceptance counters do not read
them. This is a structural programming boundary, not an adversarial security sandbox.

The full validation path reuses the approved source checksum/size/name and
consumed-byte stability gates. It streams the existing canonical parser directly;
no canonical or model-ready dataset is rewritten.

## Exact feature definitions

For a current transfer at step `t`, every historical definition below uses only
events with `event.step < t`. Amount histories include every transaction type.

| Core feature | Definition |
|---|---|
| `amount` | Current requested transfer amount |
| `initiator_prior_outgoing_count` | Earlier outgoing transaction count for this initiator |
| `initiator_prior_outgoing_transfer_count` | Earlier outgoing TRANSFER count for this initiator |
| `initiator_prior_outgoing_amount_total` | Exact sum of earlier outgoing amounts |
| `initiator_prior_outgoing_amount_mean` | Earlier outgoing total divided by count, under the mean policy below |
| `initiator_prior_outgoing_amount_max` | Maximum earlier outgoing amount |
| `recipient_prior_incoming_count` | Earlier incoming transaction count for this recipient |
| `initiator_prior_distinct_recipient_count` | Number of unique recipients in this initiator's earlier outgoing activity |
| `recipient_prior_distinct_initiator_count` | Number of unique initiators in this recipient's earlier incoming activity |

Enhanced adds only `initiator_balance_before` and `recipient_balance_before`.
These are the current transaction's authoritative pre-update values; negative
values are preserved. The engine never incorporates them into history. Their
availability in the synthetic source does not establish synchronous production
availability; that deployment caveat remains unchanged.

Raw IDs, absolute step, technical UUID/source order, current/historical fraud
labels, post-balances and their derivatives, and same-step/future aggregates are
not predictors. There are no additional engineered features or learned imputers.

## Two-phase step replay

1. At step `t`, committed maps and pair membership represent completed steps `< t`.
2. Calculate each eligible current transfer from committed state only.
3. Accumulate all current-step activity into separate pending sender/recipient
   aggregates and a set of newly observed pairs.
4. On arrival of a valid later-step event, merge the previous complete step's
   pending state before calculating the later event. Missing step values require
   no synthetic events; committed state simply carries forward.
5. Commit the final pending step only after successful end of input.

No current-step event can observe itself, another same-step event, or pending new
counterparties. Source row number and UUID are never consulted by the engine.
Chronological regression raises rather than sorting. Upstream parsing failure or
early closure aborts pending state and makes that replay unusable. A new replay
is required after failure; the engine is not a resumable transaction store.

The iterator can yield provisional examples before the whole source is consumed.
Consumers must exhaust it successfully and complete source-integrity checks before
accepting a run. Stage 4C publishes no example files. Stage 4E must preserve this
failure boundary when implementing persistent materialisation.

## Exact distinct state and memory

Committed state contains per-initiator count/transfer-count/sum/max/distinct-count
aggregates, per-recipient incoming/distinct counts, and **one exact set of directed
initiator-recipient pairs**. Pending state contains entity aggregates and only
pairs not yet in committed history. Repeated pairs, including within a step,
cannot inflate distinct counts. Self-transfers obey the same role-specific rules.

An internal string pool shares equal opaque ID strings among pair entries; this
is a storage optimisation, not a predictive entity encoding. No historical event,
label, balance snapshot or feature example is stored in the engine.

Memory scales with entities and distinct observed pairs plus pending aggregates,
not repeated-event count. In the worst case every transaction can create a new
pair: exact counterparties are therefore not constant-memory in arbitrary data.
`state_statistics()` exposes sizes/counts for diagnostics only, never predictors.

## Exact Decimal and cold starts

- Source amounts remain the original exact `Decimal` values.
- For addition, a local context derives sufficient precision from the operands'
  highest occupied place and lowest exponent, with room for a carry. `Inexact`
  is trapped. Neither source amounts nor historical sums are quantised or rounded.
- For **mean division only**, every call constructs an explicit local
  `decimal.Context` with **28 significant digits and ROUND_HALF_EVEN**. Division
  does not depend on ambient precision, rounding, exponent settings or traps.
- Empty history gives integer zero for counts, `Decimal(0)` for total, and
  `None` for mean and maximum. No mean/max zero-filling is performed.
- Final persistent Decimal feature serialisation belongs to Stage 4E. The
  acceptance hash's internal numeric token is a diagnostic, not that file contract.

## Chronological evaluation continuity

The frozen ranges remain train 0-95, validation 96-119, test 120-143. The history
engine does not receive partition names and never resets at 95/96 or 119/120.
All completed earlier unlabelled activity, including earlier holdout activity,
can affect later examples. Partition counts are assigned from lineage step
outside predictor construction. Values outside the frozen evaluation horizon
are rejected by that evaluation helper, not silently assigned to a new split.

No training, preprocessing fitting, threshold selection or fraud-performance
analysis takes place here. The six-day synthetic horizon and unresolved paper
configuration discrepancy remain limitations, not corrected data.

## Validation runbook

From the repository root, using the installed editable package or setting
`$env:PYTHONPATH = "src"` for the current PowerShell session:

```powershell
python -B -m transactionshield.feature_validation data/raw/synthetic_mobile_money_transaction_dataset.csv `
  --report-output data/interim/stage4c-validation.json
```

The optional report path must be new and below ignored `data/interim/`. Omitting
it prints the report only. A second run can use `stage4c-validation-repeat.json`.
The CLI offers no source-identity override and writes no transaction-level output.

The report checks 1,720,181 consumed rows, 569,328 eligible examples and frozen
partition counts (375,732 / 94,503 / 99,093). It records predictor schema, zero/null
counts, aggregate-state sizes and independent Core/Enhanced diagnostic SHA-256
values. Each digest binds exact numeric feature values to technical transaction
identity in source replay order, without treating that identity as a predictor.
Equivalent Decimal spellings share a numeric token; no float conversion is used.

Reports include source/implementation identity. Volatile elapsed time is printed
outside their deterministic content. Full repeats must agree on both diagnostic
hashes and report values. Fixture permutation tests compare examples by stable
identity instead of comparing an order-dependent stream hash.

## Tests

`python -m pytest` includes independent hand-calculated aggregates, all transaction
types, cold starts, role separation, self-transfers, repeated pairs, exhaustive
same-step permutations, future changes, label/post-balance changes, Enhanced
isolation, partition continuity, missing steps, regressions, failed input/early
closure, exact large sums, nonterminating means and HALF_EVEN ties under hostile
ambient Decimal contexts. A small seeded replay is also checked against an
independent strict-prior batch oracle. A repeated-pair workload verifies that
aggregate/pair state does not retain each historical event.

## Full-artifact acceptance results

Recovery verification completed on 2026-09-08. The recovered original report and
a fresh full replay both passed source precheck, consumed-byte digest and source
stability checks. They used the same implementation hash and are byte-identical.
These are independently calculated structural results, not fraud-performance
measurements; no test labels were used for modelling conclusions.

| Check | Verified result |
|---|---:|
| Source/canonical transactions consumed and committed | 1,720,181 |
| Eligible TRANSFER examples | 569,328 |
| Train / validation / test examples | 375,732 / 94,503 / 99,093 |
| Chronological regressions | 0 |
| Pending rows after successful completion | 0 |
| Examples with no prior outgoing history | 5,297 |
| Examples with no prior outgoing TRANSFER history | 13,004 |
| Examples with no prior incoming history | 10,605 |
| Null historical mean / maximum | 5,297 each |
| Null values in other Core fields | 0 |
| Initiator / recipient entities retained | 13,462 / 16,731 |
| Exact directed counterparty pairs retained | 1,073,021 |

Cold-start and null counts describe emitted examples, not unique accounts.
Strict prior-step semantics, both partition boundaries, non-transfer history,
forbidden-field isolation and exact arithmetic are additionally verified by the
adversarial fixture tests and independent small-replay oracle; full-run counts
and repeat hashes alone would not establish those properties.

Both runs produced these SHA-256 values:

- Core diagnostics: `256bdaa32d81e2f6c2c3ddd1780aee5b37695951d9fa63eef5e805c3952c4df5`
- Enhanced diagnostics: `011f5c488f9a1ed5cc1669c1d6023e719abcff2a873e30703e6dd7fc688dafd7`
- Complete report file: `3e2e90da777e3fae788c9987bbe1823eb7112a1d01bc9a8ac7e82c6633e7e388`
- Implementation: `10cbb8a38422bcc21d76a93f9a55bcd35deac04b9e7b5f698722d6b2a38ad52e`
- Source: `da951eb95735da96271740a3e66b676b342d3831ce3111cd19dbfa020d3bd0a7`

The fresh replay took 171.927 seconds. Windows process peak working set was
138,530,816 bytes (approximately 132.1 MiB), including Python and the parser, not
just history state. The original run's timing/memory measurements could not be
recovered. These figures are local observations, not portable performance bounds.
Reports remain ignored under `data/interim/`; neither run persisted feature rows.
