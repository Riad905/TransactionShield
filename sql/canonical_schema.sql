-- TransactionShield Stage 3 frozen canonical PostgreSQL schema design.
-- Design only: this file has not been executed against PostgreSQL.

CREATE SCHEMA IF NOT EXISTS transactionshield;

CREATE TABLE transactionshield.dataset_artifact (
    artifact_id UUID PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE
        CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    filename TEXT NOT NULL
        CHECK (length(filename) > 0),
    byte_size BIGINT NOT NULL
        CHECK (byte_size > 0),
    repository_doi TEXT NOT NULL
        CHECK (length(repository_doi) > 0),
    repository_version INTEGER NOT NULL
        CHECK (repository_version > 0),
    retrieved_on DATE NOT NULL,
    source_licence TEXT NOT NULL
        CHECK (length(source_licence) > 0)
);

CREATE TABLE transactionshield.canonical_transaction (
    transaction_id UUID PRIMARY KEY,
    artifact_id UUID NOT NULL
        REFERENCES transactionshield.dataset_artifact (artifact_id),
    source_row_number BIGINT NOT NULL
        CHECK (source_row_number >= 2),
    step INTEGER NOT NULL
        CHECK (step >= 0),
    transaction_type TEXT NOT NULL
        CHECK (
            transaction_type IN (
                'DEBIT',
                'DEPOSIT',
                'PAYMENT',
                'TRANSFER',
                'WITHDRAWAL'
            )
        ),
    amount NUMERIC NOT NULL
        CHECK (amount > 0),
    initiator_id TEXT NOT NULL
        CHECK (length(initiator_id) > 0),
    initiator_balance_before NUMERIC NOT NULL,
    initiator_balance_after NUMERIC NOT NULL,
    recipient_id TEXT NOT NULL
        CHECK (length(recipient_id) > 0),
    recipient_balance_before NUMERIC NOT NULL,
    recipient_balance_after NUMERIC NOT NULL,
    is_fraud SMALLINT NOT NULL
        CHECK (is_fraud IN (0, 1)),
    UNIQUE (artifact_id, source_row_number)
);

COMMENT ON COLUMN transactionshield.canonical_transaction.transaction_id IS
    'Deterministic UUIDv5 lineage key; never a temporal-ordering field.';
COMMENT ON COLUMN transactionshield.canonical_transaction.source_row_number IS
    'Logical CSV record number with the header counted as record 1; lineage only.';
COMMENT ON COLUMN transactionshield.canonical_transaction.initiator_balance_after IS
    'Preserved post-event source value; forbidden as a predictive feature.';
COMMENT ON COLUMN transactionshield.canonical_transaction.recipient_balance_after IS
    'Preserved post-event source value; forbidden as a predictive feature.';
COMMENT ON COLUMN transactionshield.canonical_transaction.is_fraud IS
    'Preserved target label; forbidden as a predictive feature or history input.';
