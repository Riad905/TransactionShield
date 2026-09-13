"""Stage 4D: explicit PostgreSQL transactions, bounded batches and read-back.

Run from this repository (editable installation); SQL files are reviewed source,
not user-supplied queries. The optional driver is imported only on connection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid5

from transactionshield.canonical import CANONICAL_COLUMNS, iter_canonical_records
from transactionshield.contracts import TRANSACTION_ID_NAMESPACE, evaluation_partition
from transactionshield.feature_validation import APPROVED_PARTITION_COUNTS, _numeric_token
from transactionshield.features import (
    CORE_FEATURE_NAMES, ENHANCED_ADDITIONAL_NAMES, FEATURE_CONTRACT_VERSION,
    iter_feature_examples,
)
from transactionshield.pipeline import REPOSITORY_ROOT, code_identity
from transactionshield.validation import APPROVED_ARTIFACT, IntegrityError, Reconciliation, verified_source

MIGRATIONS = (REPOSITORY_ROOT / 'sql' / 'canonical_schema.sql',
              REPOSITORY_ROOT / 'sql' / '002_persistence.sql')
LOCK_KEY = 904004  # Serialize this small project's migrations/loads; not a global DB lock.
DEFAULT_BATCH_SIZE = 1000


def connect(dsn: str | None = None):
    """Never echo configuration or driver exceptions containing connection details."""
    configuration = dsn if dsn is not None else os.environ.get('TRANSACTIONSHIELD_DATABASE_DSN')
    if not configuration:
        raise RuntimeError('Set TRANSACTIONSHIELD_DATABASE_DSN explicitly; no default database is used')
    try:
        import psycopg
    except ImportError:
        raise RuntimeError('Install the optional postgres dependency before connecting') from None
    try:
        return psycopg.connect(configuration, autocommit=True, connect_timeout=5)
    except Exception:
        raise RuntimeError('PostgreSQL connection failed; check local configuration privately') from None


def _idle_connection(connection):
    if not connection.autocommit or connection.info.transaction_status != 0:
        raise ValueError('Use an idle autocommit connection; this module owns its transactions')


def _migration_hashes():
    return [(number, hashlib.sha256(path.read_bytes()).hexdigest())
            for number, path in enumerate(MIGRATIONS, 1)]


def persistence_identity():
    payload = [code_identity()['implementation_sha256'], _migration_hashes()]
    return hashlib.sha256(json.dumps(payload, separators=(',', ':')).encode()).hexdigest()


def apply_schema(connection):
    """Atomic, checksum-tracked schema creation; refuse untracked existing schemas."""
    _idle_connection(connection)
    with connection.transaction():
        connection.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK_KEY,))
        exists = connection.execute('SELECT to_regnamespace(%s)', ('transactionshield',)).fetchone()[0]
        scripts = [path.read_bytes() for path in MIGRATIONS]
        hashes = [(number, hashlib.sha256(script).hexdigest()) for number, script in enumerate(scripts, 1)]
        if exists is not None:
            tracked = connection.execute('SELECT to_regclass(%s)',
                                         ('transactionshield.schema_migration',)).fetchone()[0]
            if tracked is None:
                raise IntegrityError('Existing schema is not migration-tracked; no automatic adoption')
            actual = connection.execute(
                'SELECT version, sha256 FROM transactionshield.schema_migration ORDER BY version'
            ).fetchall()
            if actual != hashes:
                raise IntegrityError('Schema migration checksum/version mismatch; manual review required')
            return
        # Static repository DDL has no data values and is intentionally not formatted.
        for script in scripts:
            connection.execute(script.decode('utf-8'))
        connection.execute('CREATE TABLE transactionshield.schema_migration '
                           '(version INTEGER PRIMARY KEY, sha256 TEXT NOT NULL)')
        with connection.cursor() as cursor:
            cursor.executemany('INSERT INTO transactionshield.schema_migration VALUES (%s, %s)', hashes)
        if hashes != _migration_hashes():
            raise IntegrityError('Migration files changed during schema creation')


def _insert(table, columns):
    # Only module-owned constant table/column names call this helper, never data.
    return ('INSERT INTO transactionshield.' + table + ' (' + ', '.join(columns)
            + ') VALUES (' + ', '.join(['%s'] * len(columns)) + ')')


CANONICAL_INSERT = _insert('canonical_transaction', CANONICAL_COLUMNS)
LINEAGE_INSERT = _insert('feature_lineage', ('transaction_id', 'artifact_id', 'step', 'transaction_type', 'partition'))
CORE_INSERT = _insert('core_feature', ('transaction_id', *CORE_FEATURE_NAMES))
ENHANCED_INSERT = _insert('enhanced_feature', ('transaction_id', *ENHANCED_ADDITIONAL_NAMES))
ARTIFACT_INSERT = _insert('dataset_artifact', ('artifact_id', 'sha256', 'filename', 'byte_size',
                                            'repository_doi', 'repository_version', 'retrieved_on', 'source_licence'))
COMPLETED_INSERT = _insert('completed_load', ('artifact_id', 'feature_contract', 'implementation_sha256',
                                            'canonical_count', 'feature_count', 'canonical_sha256',
                                            'core_sha256', 'enhanced_sha256'))

CANONICAL_SELECT = ('SELECT ' + ', '.join(CANONICAL_COLUMNS)
                    + ' FROM transactionshield.canonical_transaction WHERE artifact_id = %s ORDER BY source_row_number')
CORE_SELECT = ('SELECT c.transaction_id, ' + ', '.join('c.' + name for name in CORE_FEATURE_NAMES)
               + ', l.partition FROM transactionshield.core_feature c '
               'JOIN transactionshield.feature_lineage l USING (transaction_id) '
               'JOIN transactionshield.canonical_transaction t USING (transaction_id) '
               'WHERE l.artifact_id = %s ORDER BY t.source_row_number')
ENHANCED_SELECT = ('SELECT c.transaction_id, ' + ', '.join('c.' + name for name in CORE_FEATURE_NAMES)
                   + ', e.initiator_balance_before, e.recipient_balance_before '
                   'FROM transactionshield.core_feature c '
                   'JOIN transactionshield.enhanced_feature e USING (transaction_id) '
                   'JOIN transactionshield.canonical_transaction t USING (transaction_id) '
                   'WHERE t.artifact_id = %s ORDER BY t.source_row_number')


def canonical_values(row):
    """Typed values, not csv_values(): Decimal and opaque text stay unchanged."""
    values = tuple(getattr(row, name) for name in CANONICAL_COLUMNS)
    _check_numeric(values)
    return values


def _check_numeric(values):
    # Unconstrained NUMERIC still has implementation limits; reject, never round.
    for value in values:
        if isinstance(value, float):
            raise ValueError('Binary floats are not supported for persistence')
        if isinstance(value, Decimal):
            if not value.is_finite() or value.adjusted() >= 131072 or value.as_tuple().exponent < -16383:
                raise ValueError('Decimal exceeds finite PostgreSQL NUMERIC storage limits')


def example_values(example):
    if example.enhanced is None:
        raise ValueError('Persistence requires both explicitly separated feature tiers')
    identity = example.lineage.transaction_id
    lineage = (identity, example.lineage.artifact_id, example.lineage.step, 'TRANSFER',
               evaluation_partition(example.lineage.step))
    core = (identity, *(getattr(example.core, name) for name in CORE_FEATURE_NAMES))
    enhanced = (identity, *(getattr(example.enhanced, name) for name in ENHANCED_ADDITIONAL_NAMES))
    _check_numeric(core)
    _check_numeric(enhanced)
    return lineage, core, enhanced


def _hash_row(digest, values):
    tokens = []
    for value in values:
        if isinstance(value, float):
            raise IntegrityError('Binary float encountered in persistence read-back')
        tokens.append(str(value) if isinstance(value, UUID) else _numeric_token(value))
    digest.update((json.dumps(tokens, separators=(',', ':'), ensure_ascii=True) + '\n').encode())


@dataclass
class Diagnostics:
    canonical_count: int = 0
    feature_count: int = 0
    enhanced_count: int = 0
    partitions: Counter = field(default_factory=Counter)
    null_counts: Counter = field(default_factory=Counter)
    canonical_digest: object = field(default_factory=hashlib.sha256)
    core_digest: object = field(default_factory=hashlib.sha256)
    enhanced_digest: object = field(default_factory=hashlib.sha256)

    def canonical(self, values):
        self.canonical_count += 1
        _hash_row(self.canonical_digest, values)

    def core(self, values, partition):
        self.feature_count += 1
        self.partitions[partition] += 1
        for name, value in zip(CORE_FEATURE_NAMES, values[1:], strict=True):
            self.null_counts[name] += value is None
        _hash_row(self.core_digest, values)

    def enhanced(self, values):
        self.enhanced_count += 1
        _hash_row(self.enhanced_digest, values)

    def report(self):
        return {'canonical_count': self.canonical_count, 'feature_count': self.feature_count,
                'enhanced_count': self.enhanced_count,
                'partitions': {name: self.partitions[name] for name in APPROVED_PARTITION_COUNTS},
                'null_counts': {name: self.null_counts[name] for name in CORE_FEATURE_NAMES},
                'canonical_sha256': self.canonical_digest.hexdigest(),
                'core_sha256': self.core_digest.hexdigest(),
                'enhanced_sha256': self.enhanced_digest.hexdigest()}


class BatchWriter:
    def __init__(self, cursor, batch_size):
        if type(batch_size) is not int or not 1 <= batch_size <= 10000:
            raise ValueError('batch_size must be an integer from 1 to 10000')
        self.cursor, self.batch_size = cursor, batch_size
        self.canonical_rows, self.examples = [], []

    def canonical(self, values):
        self.canonical_rows.append(values)
        if len(self.canonical_rows) >= self.batch_size:
            self.flush_canonical()

    def feature(self, values):
        self.examples.append(values)
        if len(self.examples) >= self.batch_size:
            self.flush()

    def flush_canonical(self):
        if self.canonical_rows:
            self.cursor.executemany(CANONICAL_INSERT, self.canonical_rows)
            self.canonical_rows.clear()

    def flush(self):
        self.flush_canonical()  # Parent keys must exist before child inserts.
        if self.examples:
            for index, query in enumerate((LINEAGE_INSERT, CORE_INSERT, ENHANCED_INSERT)):
                self.cursor.executemany(query, [values[index] for values in self.examples])
            self.examples.clear()


def readback(connection, artifact_id):
    """Server-side cursors bound client memory; no labels enter feature replay."""
    observed = Diagnostics()
    for index, query in enumerate((CANONICAL_SELECT, CORE_SELECT, ENHANCED_SELECT)):
        with connection.cursor(name='stage4d_readback') as cursor:
            cursor.itersize = DEFAULT_BATCH_SIZE
            cursor.execute(query, (artifact_id,))
            for values in cursor:
                if index == 0:
                    observed.canonical(values)
                elif index == 1:
                    observed.core(values[:-1], values[-1])
                else:
                    observed.enhanced(values)
    lineage_count = connection.execute(
        'SELECT count(*) FROM transactionshield.feature_lineage WHERE artifact_id = %s',
        (artifact_id,)).fetchone()[0]
    if lineage_count != observed.feature_count:
        raise IntegrityError('Feature lineage contains incomplete examples')
    return observed.report()


def load_artifact(connection, source, *, contract=APPROVED_ARTIFACT,
                  expected_partitions=None, batch_size=DEFAULT_BATCH_SIZE):
    """All-or-nothing source + both tiers. Explicit alternate contracts are fixtures.

    Reloads revalidate the complete source and database contents; never overwrite.
    Caller must apply_schema first. No commit occurs inside the source guard.
    """
    _idle_connection(connection)
    if type(batch_size) is not int or not 1 <= batch_size <= 10000:
        raise ValueError('batch_size must be an integer from 1 to 10000')
    expected_partitions = APPROVED_PARTITION_COUNTS if expected_partitions is None else expected_partitions
    artifact_id = uuid5(TRANSACTION_ID_NAMESPACE, contract.sha256)
    identity = persistence_identity()
    with connection.transaction():
        connection.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK_KEY,))
        if connection.execute('SELECT version, sha256 FROM transactionshield.schema_migration ORDER BY version').fetchall() != _migration_hashes():
            raise IntegrityError('Apply/verify the approved schema before loading')
        existing = connection.execute(
            'SELECT feature_contract, implementation_sha256, canonical_count, feature_count, '
            'canonical_sha256, core_sha256, enhanced_sha256 '
            'FROM transactionshield.completed_load WHERE artifact_id = %s', (artifact_id,)
        ).fetchone()
        if existing is not None and existing[:2] != (FEATURE_CONTRACT_VERSION, identity):
            raise IntegrityError('Existing load uses a different implementation; no automatic replacement')
        expected = Diagnostics()
        reconciliation = Reconciliation()
        with connection.cursor() as cursor:
            writer = BatchWriter(cursor, batch_size) if existing is None else None
            metadata = (artifact_id, contract.sha256, contract.filename, contract.byte_size,
                        contract.repository_doi, contract.repository_version,
                        date.fromisoformat(contract.retrieved_on), contract.source_licence)
            if writer:
                cursor.execute(ARTIFACT_INSERT, metadata)
            else:
                actual_metadata = connection.execute(
                    'SELECT artifact_id, sha256, filename, byte_size, repository_doi, repository_version, '
                    'retrieved_on, source_licence FROM transactionshield.dataset_artifact WHERE artifact_id = %s',
                    (artifact_id,)).fetchone()
                if actual_metadata != metadata:
                    raise IntegrityError('Existing artifact metadata differs')
            with verified_source(Path(source).resolve(strict=True), contract) as stream:
                def rows():
                    for row in iter_canonical_records(stream, contract.sha256):
                        reconciliation.observe(row)  # Targets used only for source reconciliation.
                        values = canonical_values(row)
                        expected.canonical(values)
                        if writer:
                            writer.canonical(values)
                        yield row
                for example in iter_feature_examples(rows(), enhanced=True):
                    lineage, core, enhanced = example_values(example)
                    expected.core(core, lineage[-1])
                    expected.enhanced((*core, *enhanced[1:]))
                    if writer:
                        writer.feature((lineage, core, enhanced))
            reconciliation.verify(contract)
            report = expected.report()
            if report['partitions'] != expected_partitions or report['feature_count'] != sum(expected_partitions.values()):
                raise IntegrityError('Feature population/splits differ from acceptance contract')
            if writer:
                writer.flush()
            if readback(connection, artifact_id) != report:
                raise IntegrityError('Database read-back differs from source/features; load rejected')
            if persistence_identity() != identity:
                raise IntegrityError('Implementation changed during persistence')
            completion = (FEATURE_CONTRACT_VERSION, identity, report['canonical_count'], report['feature_count'],
                          report['canonical_sha256'], report['core_sha256'], report['enhanced_sha256'])
            if existing is not None:
                if existing != completion:
                    raise IntegrityError('Existing completion record differs from verified contents')
            else:
                cursor.execute(COMPLETED_INSERT, (artifact_id, *completion))
    return {'status': 'verified_existing' if existing is not None else 'complete',
            'artifact_id': str(artifact_id), 'implementation_sha256': identity, **report}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('schema', 'load'))
    parser.add_argument('--source', type=Path)
    args = parser.parse_args(argv)
    if args.action == 'load' and args.source is None:
        parser.error('load requires --source')
    started = time.perf_counter()
    try:
        with connect() as connection:
            if args.action == 'schema':
                apply_schema(connection)
                report = {'status': 'schema_verified'}
            else:
                report = load_artifact(connection, args.source)
    except Exception:
        # Driver errors may contain DSNs, passwords, SQL values or source IDs.
        print('PostgreSQL operation failed; no successful load reported. Check configuration and integrity privately.', file=sys.stderr)
        return 1
    print(json.dumps({'elapsed_seconds': round(time.perf_counter() - started, 3), **report}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
