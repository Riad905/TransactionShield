# Stage 4D: PostgreSQL persistence

## Status

**All five genuine PostgreSQL integration tests are verified in CI** against
the Ubuntu/PostgreSQL 17 service. See the [observed run evidence](portfolio-finalisation.md).
No SQL defects or test changes were needed. Full-artifact database acceptance
remains pending: the 1,720,181-row PostgreSQL load has not been performed.

The local-environment findings are historical. Before CI verification on
2026-09-13, real PostgreSQL integration had not run. On 2026-09-11 the
environment still had no PostgreSQL server, service, default-port listener, client
tools or Docker executable/service. Psycopg 3.3.5 and its binary extra were installed
in the ignored project virtual environment; no database server was installed.
There is therefore no existing local server to start without additional software.
The five opt-in integration tests skip when
no test database is configured; those skips are not evidence of database success.

The approved Stage 4C commit was `3cedc59b557dd857b9875f54d8352aa2eba06567`.
Its 155 tests passed before these changes. Stage 4B/4C parsing and feature
definitions are reused unchanged. There is no model, API, deployment, ORM,
container or Stage 4E feature-file format in this work.

## Why add a database?

Local CSVs remain useful immutable evidence. PostgreSQL adds relational keys,
constraints, transactional loading and indexed access without changing how
features are calculated. Python still performs the approved completed-step replay;
this stage does not introduce a second SQL implementation of feature arithmetic.

## Schema and separation

| Relation | Contents and role |
|---|---|
| `dataset_artifact` | Checksum-bound source identity and provenance |
| `canonical_transaction` | All canonical rows, opaque IDs, step, source row, balances and original label |
| `feature_lineage` | Technical key, artifact, step, exact TRANSFER eligibility and frozen split |
| `core_feature` | Technical join key plus exactly nine approved Core fields |
| `enhanced_feature` | Same key plus only the two authoritative current pre-balances |
| `completed_load` | Verified counts, feature contract, implementation identity and content hashes |
| `schema_migration` | Applied migration numbers and SQL byte checksums |

Primary/foreign keys enforce identity and parent-child integrity. The composite
feature-lineage foreign key binds eligibility and step to the canonical record.
Its CHECK constraint permits only train 0-95, validation 96-119 and test 120-143.
Canonical steps retain their original broader INTEGER domain. Features do not
reset at split boundaries; every transaction type enters history.

`core_predictors` exposes only the nine predictors. `enhanced_predictors` exposes
the same nine plus two pre-balances. Neither view contains target, IDs, step,
source-row order or post-balances. `transaction_target` is a separate target
projection; the source label remains preserved in the approved canonical table.
This is structural separation, not an access-control security boundary. Do not
join predictor-only views to labels by row position: any future labelled reader
must join the underlying tables by technical identity and select fields explicitly.

Indexes support artifact/chronological scans, transfer access and split filtering.
No account graph, entity encoding or extra model feature is introduced.

## Money and nulls

Money uses unconstrained PostgreSQL `NUMERIC`; Psycopg adapts Python `Decimal`
without a float conversion. Negative balances and zero remain valid. Source
amounts remain positive. Empty-history mean/max remain SQL NULL; counts/totals
remain zero. The database does not recompute means: Stage 4C's explicit 28-digit
ROUND_HALF_EVEN result is persisted unchanged.

Unconstrained NUMERIC still has implementation limits (131,072 integer digits,
16,383 fractional digits). The adapter rejects unsupported/non-finite Decimal
values instead of quantising them. SQL also rejects numeric NaN/infinities.
Numeric equality is preserved, not every original textual spelling: leading
plus signs and signed-zero spelling remain available in the raw artifact and
Stage 4B CSV, not guaranteed in PostgreSQL NUMERIC.

References: [Psycopg numeric adaptation](https://www.psycopg.org/psycopg3/docs/basic/adapt.html)
and [PostgreSQL numeric types](https://www.postgresql.org/docs/18/datatype-numeric.html).

## Loading, failure and repeat execution

The module requires an idle autocommit connection, then explicitly owns one
transaction for the whole load. Autocommit does not commit individual batches
inside that transaction. Successful context exit commits; an exception requests
rollback, including after the final batch or completion insert.

1. Acquire a transaction-scoped advisory lock and verify migration checksums.
2. Check whether this artifact already has a completed load.
3. Verify source bytes and replay all canonical rows through the existing engine.
4. For a new load, insert parameterised batches (default 1,000, maximum 10,000).
   Insert canonical parents before lineage, Core and Enhanced children.
5. Finish the source guard and verify source counts and frozen feature splits.
6. Read database values through server-side cursors and compare counts, splits,
   nulls and three numeric-content hashes against the streamed inputs.
7. Insert completion metadata last, then commit the transaction.

Read-back also checks that lineage has no incomplete extra examples. Hash order
uses source row number only for deterministic reconciliation, never as a feature
or a within-step chronology assumption. Each content hash includes technical
identity separately from feature values. These are database diagnostics, not
Stage 4E serialisation or byte hashes of PostgreSQL storage.

A repeat with identical source and implementation performs a full replay and
read-back without writing data. Differences in metadata, feature version,
implementation or contents are rejected, never overwritten. A stray partial
artifact without a completion record causes a key conflict rather than being
adopted. Different implementations require an explicit future migration/rebuild
decision; this stage provides no automatic replacement or deletion command.

The lock serializes this project's loaders and schema setup; it is not a security
mechanism against arbitrary SQL writers. Use a dedicated database with controlled
write access. Constraints and completion metadata are not tamper-proof.

Client memory is batch buffers plus the existing entity/distinct-pair history;
exact pair history can grow with data size. Server-side read-back avoids fetching
all rows into Python. One large transaction trades simple atomicity for database
WAL/disk use, lock duration and potentially expensive rollback. Live performance
and memory have not been measured.

Reference: [Psycopg transaction contexts](https://www.psycopg.org/psycopg3/docs/basic/transactions.html).

## Schema setup and optional driver

`sql/canonical_schema.sql` is unchanged and serves as migration 1.
`sql/002_persistence.sql` adds the Stage 4D relations. `apply_schema` runs both
atomically on a fresh schema and records their checksums. Repeated setup verifies
them. An untracked existing schema or changed migration is refused for manual
review. This is a small bootstrap, not a general schema-upgrade framework.

One optional dependency family is declared: `psycopg[binary]>=3.2,<4`. Psycopg 3
provides parameter binding, Decimal adaptation and transaction/server-cursor
support. The binary extra avoids local compiler/libpq setup. It is not required
or imported for ordinary local contract tests. No ORM or second database library is used.

After a separate PostgreSQL environment is provided, use this repository's virtual
environment and editable installation:

```powershell
python -m pip install -e ".[dev,postgres]"
python -m transactionshield.postgres schema
python -m transactionshield.postgres load --source data/raw/synthetic_mobile_money_transaction_dataset.csv
```

Configure `TRANSACTIONSHIELD_DATABASE_DSN` privately before these commands; there
is no default database or command-line DSN option. Library callers may pass a DSN
explicitly. Do not paste it into logs, documentation or tracked files. CLI failures
print a generic message rather than driver diagnostics that could include secrets
or transaction values. Library callers must also avoid logging raw driver errors.
SQL files are resolved from the repository: a standalone wheel deployment is not
supported or claimed. The schema and loader functions ran on small CI fixtures;
the CLI commands above have not been used for a full-data database load.

## What is tested

Local tests inspect SQL field projections/types/constraints and exercise typed
parameters, batching, integrity comparisons, chronological failure and completion
ordering. Small connection doubles record commit/rollback orchestration; they do
not emulate SQL execution, constraints, isolation or database durability.

The five genuine integration tests cover schema creation, actual NUMERIC storage,
fixture load/reload, late-write rollback, duplicate/constraint failures and
rejection of modified stored features. Enable them only with
`TRANSACTIONSHIELD_TEST_DATABASE_DSN` pointing to a disposable database whose name
starts with `transactionshield_test` and whose `transactionshield` schema is absent:

```powershell
python -m pytest -m postgres
```

Each test creates and removes only its own fixed application schema in that
explicitly opted-in test database. Existing schemas are refused, not cleared.
A configured but inaccessible server fails the tests rather than becoming a pass.
Without configuration the tests explicitly skip. Nothing here provisions a server.

Full-data acceptance remains pending: 1,720,181 canonical rows, 569,328 features,
375,732/94,503/99,093 splits, 5,297 null means/maxima, real read-back equality and
repeat diagnostics. These are acceptance targets from Stage 4C, **not database
results**. No live load runtime, memory, rollback or throughput claim is made.

## Portfolio review and limitations

Recovery verification on 2026-09-10: **188 passed, 5 skipped (193 collected)**;
all 21 project Python files compiled; tracked and new-file whitespace checks
passed. One earlier run hit Windows access-denied on a temporary-directory rename
in an unchanged Stage 4B test. That test passed on an isolated rerun, followed by
a passing full suite; no Stage 4B code was changed. The exact filesystem-lock
cause was not established. Live PostgreSQL tests had not run at that historical
checkpoint; all five were subsequently verified in CI on 2026-09-13.

The implementation stays in one explicit module with two small state holders
(batch buffers and diagnostic counters), two SQL files and focused tests. No
repository/service class hierarchy, ORM, migration dependency, retry framework,
connection pool or distributed job machinery was added. Existing parser/feature
logic is reused rather than duplicated. Atomicity and read-back are deliberate
correctness protections, not deployment claims.

Stage 4E used verified local features, not a database export. Full-data PostgreSQL
acceptance still needs to run; fixture CI does not establish full-load capacity.
Also assess server disk/WAL requirements and query performance. Operational access
control, backup/restore and production deployment are not implemented. The
six-day synthetic horizon and Enhanced balance-availability caveat remain.
