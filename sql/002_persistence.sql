-- Stage 4D additions; canonical_schema.sql is the unchanged first migration.
-- NUMERIC remains unconstrained. Reject PostgreSQL's non-finite numeric values.
ALTER TABLE transactionshield.canonical_transaction
    ADD CONSTRAINT canonical_finite_money CHECK (
        amount NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)
        AND initiator_balance_before NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)
        AND initiator_balance_after NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)
        AND recipient_balance_before NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)
        AND recipient_balance_after NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)
    ),
    ADD CONSTRAINT canonical_feature_reference
        UNIQUE (transaction_id, artifact_id, step, transaction_type);

CREATE INDEX canonical_chronology ON transactionshield.canonical_transaction
    (artifact_id, step, source_row_number);
CREATE INDEX canonical_transfers ON transactionshield.canonical_transaction
    (artifact_id, step) WHERE transaction_type = 'TRANSFER';

-- This table is metadata, not a predictor table. The composite FK binds the
-- split and TRANSFER eligibility to the actual canonical transaction.
CREATE TABLE transactionshield.feature_lineage (
    transaction_id UUID PRIMARY KEY,
    artifact_id UUID NOT NULL,
    step INTEGER NOT NULL,
    transaction_type TEXT NOT NULL CHECK (transaction_type = 'TRANSFER'),
    partition TEXT NOT NULL CHECK (
        (partition = 'train' AND step BETWEEN 0 AND 95)
        OR (partition = 'validation' AND step BETWEEN 96 AND 119)
        OR (partition = 'test' AND step BETWEEN 120 AND 143)
    ),
    FOREIGN KEY (transaction_id, artifact_id, step, transaction_type)
        REFERENCES transactionshield.canonical_transaction
        (transaction_id, artifact_id, step, transaction_type)
);
CREATE INDEX feature_partition ON transactionshield.feature_lineage (artifact_id, partition, step);

CREATE TABLE transactionshield.core_feature (
    transaction_id UUID PRIMARY KEY REFERENCES transactionshield.feature_lineage (transaction_id),
    amount NUMERIC NOT NULL CHECK (amount > 0 AND amount < 'Infinity'::numeric),
    initiator_prior_outgoing_count BIGINT NOT NULL CHECK (initiator_prior_outgoing_count >= 0),
    initiator_prior_outgoing_transfer_count BIGINT NOT NULL
        CHECK (initiator_prior_outgoing_transfer_count BETWEEN 0 AND initiator_prior_outgoing_count),
    initiator_prior_outgoing_amount_total NUMERIC NOT NULL
        CHECK (initiator_prior_outgoing_amount_total >= 0 AND initiator_prior_outgoing_amount_total < 'Infinity'::numeric),
    initiator_prior_outgoing_amount_mean NUMERIC,
    initiator_prior_outgoing_amount_max NUMERIC,
    recipient_prior_incoming_count BIGINT NOT NULL CHECK (recipient_prior_incoming_count >= 0),
    initiator_prior_distinct_recipient_count BIGINT NOT NULL
        CHECK (initiator_prior_distinct_recipient_count BETWEEN 0 AND initiator_prior_outgoing_count),
    recipient_prior_distinct_initiator_count BIGINT NOT NULL
        CHECK (recipient_prior_distinct_initiator_count BETWEEN 0 AND recipient_prior_incoming_count),
    CHECK (
        (initiator_prior_outgoing_count = 0 AND initiator_prior_outgoing_amount_total = 0
            AND initiator_prior_outgoing_amount_mean IS NULL AND initiator_prior_outgoing_amount_max IS NULL)
        OR (initiator_prior_outgoing_count > 0 AND initiator_prior_outgoing_amount_total > 0
            AND initiator_prior_outgoing_amount_mean IS NOT NULL AND initiator_prior_outgoing_amount_max IS NOT NULL
            AND initiator_prior_outgoing_amount_mean > 0 AND initiator_prior_outgoing_amount_mean < 'Infinity'::numeric
            AND initiator_prior_outgoing_amount_max > 0 AND initiator_prior_outgoing_amount_max < 'Infinity'::numeric)
    )
);

CREATE TABLE transactionshield.enhanced_feature (
    transaction_id UUID PRIMARY KEY REFERENCES transactionshield.core_feature (transaction_id),
    initiator_balance_before NUMERIC NOT NULL
        CHECK (initiator_balance_before NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)),
    recipient_balance_before NUMERIC NOT NULL
        CHECK (recipient_balance_before NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric))
);

-- Explicit projection: no labels, IDs, step or post-balances in these views.
CREATE VIEW transactionshield.core_predictors AS SELECT
    amount, initiator_prior_outgoing_count, initiator_prior_outgoing_transfer_count,
    initiator_prior_outgoing_amount_total, initiator_prior_outgoing_amount_mean,
    initiator_prior_outgoing_amount_max, recipient_prior_incoming_count,
    initiator_prior_distinct_recipient_count, recipient_prior_distinct_initiator_count
    FROM transactionshield.core_feature;
CREATE VIEW transactionshield.enhanced_predictors AS SELECT
    c.amount, c.initiator_prior_outgoing_count, c.initiator_prior_outgoing_transfer_count,
    c.initiator_prior_outgoing_amount_total, c.initiator_prior_outgoing_amount_mean,
    c.initiator_prior_outgoing_amount_max, c.recipient_prior_incoming_count,
    c.initiator_prior_distinct_recipient_count, c.recipient_prior_distinct_initiator_count,
    e.initiator_balance_before, e.recipient_balance_before
    FROM transactionshield.core_feature c JOIN transactionshield.enhanced_feature e USING (transaction_id);
CREATE VIEW transactionshield.transaction_target AS
    SELECT transaction_id, is_fraud FROM transactionshield.canonical_transaction;

-- Inserted last, in the same transaction as all data. No partial-success flag.
CREATE TABLE transactionshield.completed_load (
    artifact_id UUID PRIMARY KEY REFERENCES transactionshield.dataset_artifact (artifact_id),
    feature_contract TEXT NOT NULL,
    implementation_sha256 TEXT NOT NULL CHECK (implementation_sha256 ~ '^[0-9a-f]{64}$'),
    canonical_count BIGINT NOT NULL CHECK (canonical_count > 0),
    feature_count BIGINT NOT NULL CHECK (feature_count >= 0),
    canonical_sha256 TEXT NOT NULL CHECK (canonical_sha256 ~ '^[0-9a-f]{64}$'),
    core_sha256 TEXT NOT NULL CHECK (core_sha256 ~ '^[0-9a-f]{64}$'),
    enhanced_sha256 TEXT NOT NULL CHECK (enhanced_sha256 ~ '^[0-9a-f]{64}$')
);
