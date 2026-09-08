# Scoring population and point-in-time feature contract

The population, feature exclusions, two-tier structure, and non-transfer response below are frozen Stage 3 decisions.

## Primary scoring population

The locked rule is exact and case-sensitive:

```text
eligible_for_primary_model = transactionType == "TRANSFER"
```

| Measure | Independently verified value |
|---|---:|
| Eligible transfers | 569,328 |
| Fraudulent transfers | 175,518 |
| Legitimate transfers | 393,810 |
| Fraud prevalence among transfers | 30.828977% |

Every observed fraud is a transfer. Including 1,150,853 non-transfer rows as guaranteed legitimate examples would give the primary model an easy transaction-type shortcut and would misstate its useful decision population. Non-transfer rows remain in the canonical data layer for reconciliation, operational analytics, data-quality monitoring, and possible future type-specific policies.

A future scoring API must evaluate eligibility before invoking the primary model. A structurally valid non-transfer request must not receive a fraud probability from the transfer model and must not be treated as legitimate by default. The domain response should explicitly return `eligible_for_primary_model=false`, `scoring_status=not_scored`, and a non-transfer reason, then leave routing to a separate non-ML policy. The eventual transport status and response envelope remain API-design decisions.

## Model tiers

- **Core request-time model:** uses the current transfer amount and point-in-time histories guaranteed to contain completed earlier steps only. It does not require a synchronous balance lookup.
- **Platform-state enhanced model:** may additionally use pre-transaction initiator and recipient balances only if the product contract confirms that authoritative, pre-update values can be queried synchronously at scoring time.

The tiers must be evaluated separately. The enhanced tier must not be described as deployable until its state-availability assumptions are accepted.

## Contract fields that are not direct features

| Field | Permitted use | Direct model input? |
|---|---|---|
| `transactionType` | Eligibility routing; must equal `TRANSFER` | No: constant in the eligible population |
| `initiator` | Key for strictly prior outgoing history | No |
| `recipient` | Key for strictly prior incoming/counterparty history | No |
| `step` | Temporal split, history cutoff, and point-in-time joins | No: the absolute simulator step lacks portable production meaning |
| `transaction_id` | Technical lineage and joins | No |
| `source_row_number` | Source reconciliation only | No |

## A. Request-time features

| Feature | Exact definition | Source | Availability | Intended type | Tier | Leakage rationale |
|---|---|---|---|---|---|---|
| `amount` | Amount requested for the current transfer | `amount` | In the request before decision | Numeric | Core | Current-event input; contains no outcome or future state |

The request also supplies transaction type and party IDs, but they are used only for eligibility and history lookup. The source `step` is required for offline temporal joins and evaluation, not proposed as a direct MVP predictor.

## B. Platform-state candidate features

| Feature | Exact definition | Source | Availability | Intended type | Tier | Leakage rationale |
|---|---|---|---|---|---|---|
| `initiator_balance_before` | Authoritative initiator balance immediately before applying the current transfer | `oldBalInitiator` | Synchronous platform lookup before update | Numeric | Enhanced only | Pre-event in the data, but usable only if the live platform guarantees the same snapshot semantics |
| `recipient_balance_before` | Authoritative recipient balance immediately before applying the current transfer | `oldBalRecipient` | Synchronous platform lookup before update | Numeric | Enhanced only | Recipient state may not be available to the scoring service; requires an explicit product/system assumption |

Negative balance values are retained. No clipping, zero-filling, or sign-based cleaning is permitted without a later documented decision.

## C. Strictly point-in-time historical features

For a current transaction at step `t`, every feature below uses only rows satisfying `history.step < t`. The current row, every other row at step `t`, all later rows, and every historical `isFraud` value are excluded.

During chronological validation or test replay, this history may include unlabelled transaction activity from completed earlier steps inside the same validation or test partition. Those events would already exist when a production transaction is scored. Their labels are never exposed to feature computation, and their activity does not fit or update learned preprocessing or model parameters.

| Feature | Exact definition at step `t` | Source columns | Availability | Intended type | Tier | Leakage rationale |
|---|---|---|---|---|---|---|
| `initiator_prior_outgoing_count` | Count of all earlier transactions initiated by the current initiator | `initiator`, `step` | After step `t-1` is complete | Big integer | Core | Uses ID only as a lookup key and excludes the current step |
| `initiator_prior_outgoing_transfer_count` | Count of earlier `TRANSFER` rows initiated by the current initiator | `initiator`, `transactionType`, `step` | After step `t-1` is complete | Big integer | Core | Filter is based only on prior event type |
| `recipient_prior_incoming_count` | Count of all earlier transactions received by the current recipient | `recipient`, `step` | After step `t-1` is complete | Big integer | Core | Excludes current/future recipient activity |
| `initiator_prior_outgoing_amount_mean` | Earlier outgoing amount sum divided by earlier outgoing count; null when count is zero | `initiator`, `amount`, `step` | After step `t-1` is complete | Numeric | Core | Uses only completed earlier-step amounts |
| `initiator_prior_outgoing_amount_max` | Maximum amount across earlier outgoing transactions; null when none exist | `initiator`, `amount`, `step` | After step `t-1` is complete | Numeric | Core | Cumulative maximum excludes current step |
| `initiator_prior_outgoing_amount_total` | Sum of amounts across earlier outgoing transactions | `initiator`, `amount`, `step` | After step `t-1` is complete | Numeric | Core | Cumulative sum excludes current step |
| `initiator_prior_distinct_recipient_count` | Count of distinct recipients first encountered by the initiator before `t` | `initiator`, `recipient`, `step` | After step `t-1` is complete | Big integer | Core | Counts counterparties by first-seen step, never same-step rows |
| `recipient_prior_distinct_initiator_count` | Count of distinct initiators first encountered by the recipient before `t` | `recipient`, `initiator`, `step` | After step `t-1` is complete | Big integer | Core | Counts counterparties by first-seen step, never same-step rows |

## D. Forbidden predictive inputs

| Forbidden input | Reason |
|---|---|
| `newBalInitiator`, `newBalRecipient` | Post-event state unavailable at the decision moment |
| Current `isFraud` | Target leakage |
| Historical `isFraud` aggregates | Explicitly excluded from the MVP; simulator outcomes would create label-history shortcuts |
| Future rows or future-derived aggregates | Look-ahead leakage |
| Rows from the current step | Reliable within-step order is unavailable |
| Direct encoding of raw initiator or recipient IDs | Entity memorisation and poor unseen-entity behaviour |
| `transaction_id` or `source_row_number` | Technical/source order has no predictive business meaning and is not event order |
| Any feature derived from post-balances | Outcome-derived leakage even if the raw balances themselves are omitted |

## Same-step-safe history computation

The computation contract is:

```text
source transactions
  -> aggregate by entity + step
  -> create one per-entity/per-step summary row
  -> apply cumulative windows ending at 1 PRECEDING
  -> join prior state to current transactions by entity + current step
```

For outgoing count/sum/max, aggregate current-step values first, then use a window ordered by `step` with `ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING`. The prior mean is prior cumulative sum divided by prior cumulative count. Incoming histories use the corresponding recipient-step table.

Distinct-counterparty histories require a first-seen relation: calculate `MIN(step)` for each `(initiator, recipient)` pair, count newly observed counterparties by entity and first-seen step, then cumulatively sum through `1 PRECEDING`. Summing per-step distinct counts directly is forbidden because it double-counts counterparties seen in multiple steps.

Because each window operates after collapsing an entity's activity to one row per step and excludes the current per-step row, CSV row order and technical IDs cannot leak information between transactions in the same step. Missing prior state is represented by zero for counts/totals and null for undefined means/maxima; the model preprocessing contract must distinguish those cases explicitly.

## Stage 4C implementation and approved mean arithmetic

The feature definitions above are implemented by the local `features.py` engine.
Its pending entity/step aggregates are merged only on advancement to a later
step, or successful end of input. This is the streaming equivalent of the
exclusive cumulative-window contract, not a change to it. All valid canonical
transaction types feed history; the transfer rule filters output only.

Source monetary values and historical totals remain exact `Decimal` values.
For historical means only, Stage 4C freezes **28 significant decimal digits**
with **ROUND_HALF_EVEN**, using an explicit local `decimal.Context` on every
division. No ambient process precision, binary float, quantisation or learned
imputation is used. A zero historical count yields `None` for mean and maximum;
counts and totals remain zero. Final persistent feature serialisation is deferred
to Stage 4E. See the [implementation runbook](stage4c-feature-engine.md).
