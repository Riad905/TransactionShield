"""Unit/SQL contract tests only. Doubles do not simulate PostgreSQL guarantees."""

import hashlib
import re
import sys
from contextlib import contextmanager
from dataclasses import replace
from decimal import Decimal, localcontext
from types import SimpleNamespace

import pytest

from transactionshield import postgres as pg
from transactionshield.canonical import CANONICAL_COLUMNS, iter_canonical_records
from transactionshield.features import CORE_FEATURE_NAMES, iter_feature_examples
from transactionshield.validation import IntegrityError


class ConnectionDouble:
    """Record calls and transaction exit; explicit answers, no SQL emulation."""
    autocommit = True

    def __init__(self, answers=()):
        self.info = SimpleNamespace(transaction_status=0)
        self.answers = iter(answers)
        self.calls = []
        self.commits = self.rollbacks = 0
        self.fail_query = None

    @contextmanager
    def transaction(self):
        try:
            yield
        except BaseException:
            self.rollbacks += 1
            raise
        else:
            self.commits += 1

    def execute(self, query, params=None):
        self.calls.append((query, params))
        if query == self.fail_query:
            raise RuntimeError('injected write failure')
        self.result = next(self.answers) if query.startswith('SELECT') and 'pg_advisory' not in query else None
        return self

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.result

    def executemany(self, query, rows):
        self.calls.append((query, tuple(rows)))
        if query == self.fail_query:
            raise RuntimeError('injected batch failure')

    @contextmanager
    def cursor(self):
        yield self


def fixture_values(source, contract):
    with source.open(encoding='utf-8', newline='') as stream:
        rows = list(iter_canonical_records(stream, contract.sha256))
    examples = list(iter_feature_examples(rows, enhanced=True))
    diagnostics = pg.Diagnostics()
    for row in rows:
        diagnostics.canonical(pg.canonical_values(row))
    for example in examples:
        lineage, core, enhanced = pg.example_values(example)
        diagnostics.core(core, lineage[-1])
        diagnostics.enhanced((*core, *enhanced[1:]))
    return rows, examples, diagnostics.report()


def test_schema_exact_predictor_contract_and_types():
    sql = pg.MIGRATIONS[1].read_text(encoding='utf-8')
    for view, expected in [('core_predictors', CORE_FEATURE_NAMES),
                           ('enhanced_predictors', (*CORE_FEATURE_NAMES, *pg.ENHANCED_ADDITIONAL_NAMES))]:
        projection = re.search(r'CREATE VIEW transactionshield\.' + view + r' AS SELECT\s+(.*?)\s+FROM', sql, re.S)[1]
        assert tuple(item.strip().split('.')[-1] for item in projection.split(',')) == expected
    for name in (*CORE_FEATURE_NAMES, *pg.ENHANCED_ADDITIONAL_NAMES):
        kind = 'BIGINT' if name.endswith('count') else 'NUMERIC'
        assert re.search(r'\b' + name + r' ' + kind + r'\b', sql)
    assert 'NUMERIC(' not in sql.upper()
    assert 'FLOAT' not in sql.upper() and 'DOUBLE PRECISION' not in sql.upper()
    assert 'initiator_prior_outgoing_amount_mean IS NULL' in sql
    assert 'initiator_prior_outgoing_amount_max IS NULL' in sql
    assert "transaction_type = 'TRANSFER'" in sql
    assert all(bounds in sql for bounds in ('BETWEEN 0 AND 95', 'BETWEEN 96 AND 119', 'BETWEEN 120 AND 143'))
    assert 'FOREIGN KEY (transaction_id, artifact_id, step, transaction_type)' in sql
    assert 'REFERENCES transactionshield.core_feature' in sql
    assert 'SELECT transaction_id, is_fraud' in sql
    assert 'UNIQUE (transaction_id, artifact_id, step, transaction_type)' in sql
    assert 'CREATE INDEX canonical_chronology' in sql


def test_parameter_projection_decimal_nulls_and_injection_like_identifiers(postgres_artifact):
    source, contract, _ = postgres_artifact()
    rows, examples, _ = fixture_values(source, contract)
    values = pg.canonical_values(rows[0])
    assert values[6] == ' 001 ' and values[9] == "B';--"
    assert values[7] == Decimal('-10.000') and values[10] == Decimal(0)
    assert all(isinstance(values[index], Decimal) for index in (5, 7, 8, 10, 11))
    assert "B';--" not in pg.CANONICAL_INSERT
    for query, width in [(pg.CANONICAL_INSERT, 13), (pg.LINEAGE_INSERT, 5),
                         (pg.CORE_INSERT, 10), (pg.ENHANCED_INSERT, 3)]:
        assert query.count('%s') == width
    lineage, core, enhanced = pg.example_values(examples[0])
    assert core[5:7] == (None, None)
    assert enhanced[1:] == (Decimal('-10.000'), Decimal(0))
    assert lineage[-2:] == ('TRANSFER', 'train')
    assert 'is_fraud' not in pg.CORE_INSERT and 'step' not in pg.CORE_INSERT
    with pytest.raises(ValueError, match='both'):
        pg.example_values(replace(examples[0], enhanced=None))


def test_batches_are_bounded_and_parent_before_child(postgres_artifact):
    source, contract, _ = postgres_artifact()
    rows, examples, _ = fixture_values(source, contract)
    by_id = {e.lineage.transaction_id: e for e in examples}
    connection = ConnectionDouble()
    writer = pg.BatchWriter(connection, 2)
    for row in rows:
        writer.canonical(pg.canonical_values(row))
        if row.transaction_id in by_id:
            writer.feature(pg.example_values(by_id[row.transaction_id]))
        assert len(writer.canonical_rows) < 2 and len(writer.examples) < 2
    writer.flush()
    canonical_ids = set()
    for query, batch in connection.calls:
        assert 1 <= len(batch) <= 2
        if query == pg.CANONICAL_INSERT:
            canonical_ids.update(row[0] for row in batch)
        else:
            assert all(row[0] in canonical_ids for row in batch)
    assert sum(len(b) for q, b in connection.calls if q == pg.CANONICAL_INSERT) == 6
    assert sum(len(b) for q, b in connection.calls if q == pg.CORE_INSERT) == 4


@pytest.mark.parametrize('size', [0, -1, True, 10001])
def test_invalid_batch_size_rejected(size):
    with pytest.raises(ValueError):
        pg.BatchWriter(ConnectionDouble(), size)


def test_digest_exact_numeric_equality_and_no_float():
    with localcontext() as context:
        context.prec = 1
        first, second = hashlib.sha256(), hashlib.sha256()
        pg._hash_row(first, (Decimal('12345678901234567890.120'), Decimal('-0.00'), None))
        pg._hash_row(second, (Decimal('12345678901234567890.12'), Decimal(0), None))
        assert first.digest() == second.digest()
    with pytest.raises(IntegrityError, match='float'):
        pg._hash_row(hashlib.sha256(), (1.2,))


@pytest.mark.parametrize('value', [1.2, Decimal('NaN'), Decimal('Infinity'), Decimal('1E-16384'), Decimal('1E131072')])
def test_unsupported_numeric_values_fail_instead_of_rounding(value):
    with pytest.raises(ValueError):
        pg._check_numeric((value,))


def test_schema_creation_and_repeat_orchestration():
    connection = ConnectionDouble([(None,)])
    pg.apply_schema(connection)
    assert connection.commits == 1 and connection.rollbacks == 0
    assert all((path.read_text(encoding='utf-8'), None) in connection.calls for path in pg.MIGRATIONS)
    repeated = ConnectionDouble([('transactionshield',), ('schema_migration',), pg._migration_hashes()])
    pg.apply_schema(repeated)
    assert repeated.commits == 1
    assert not any(q.startswith(('CREATE', 'ALTER', 'INSERT')) for q, _ in repeated.calls)


@pytest.mark.parametrize('answers', [
    [('transactionshield',), (None,)],
    [('transactionshield',), ('schema_migration',), [(1, 'wrong')]],
])
def test_existing_untracked_or_changed_schema_not_adopted(answers):
    connection = ConnectionDouble(answers)
    with pytest.raises(IntegrityError):
        pg.apply_schema(connection)
    assert connection.rollbacks == 1 and connection.commits == 0


def test_schema_failure_requests_rollback():
    connection = ConnectionDouble([(None,)])
    connection.fail_query = pg.MIGRATIONS[1].read_text(encoding='utf-8')
    with pytest.raises(RuntimeError):
        pg.apply_schema(connection)
    assert connection.rollbacks == 1 and connection.commits == 0


def test_caller_transaction_not_silently_committed():
    connection = ConnectionDouble()
    connection.autocommit = False
    with pytest.raises(ValueError, match='idle'):
        pg.apply_schema(connection)
    connection.autocommit = True
    connection.info.transaction_status = 2
    with pytest.raises(ValueError, match='idle'):
        pg.load_artifact(connection, 'unused')
    assert connection.calls == []


def test_load_and_repeat_revalidate_without_writes(postgres_artifact, monkeypatch):
    source, contract, partitions = postgres_artifact()
    _, _, report = fixture_values(source, contract)
    monkeypatch.setattr(pg, 'readback', lambda *args: report)
    connection = ConnectionDouble([pg._migration_hashes(), None])
    first = pg.load_artifact(connection, source, contract=contract, expected_partitions=partitions, batch_size=2)
    assert first['status'] == 'complete'
    assert connection.commits == 1
    completion = next(params for query, params in connection.calls if query == pg.COMPLETED_INSERT)
    metadata = next(params for query, params in connection.calls if query == pg.ARTIFACT_INSERT)
    repeated = ConnectionDouble([pg._migration_hashes(), completion[1:], metadata])
    second = pg.load_artifact(repeated, source, contract=contract, expected_partitions=partitions)
    assert second == {**first, 'status': 'verified_existing'}
    assert not any(query.startswith(('INSERT', 'UPDATE', 'DELETE')) for query, _ in repeated.calls)
    assert second['partitions'] == {'train': 2, 'validation': 1, 'test': 1}
    assert second['null_counts']['initiator_prior_outgoing_amount_mean'] == 1


@pytest.mark.parametrize('failure', ['batch', 'readback', 'splits', 'source_exit', 'code_change', 'completion'])
def test_load_failure_never_marks_complete(postgres_artifact, monkeypatch, failure):
    source, contract, partitions = postgres_artifact()
    _, _, report = fixture_values(source, contract)
    monkeypatch.setattr(pg, 'readback', lambda *args: report if failure != 'readback' else {})
    connection = ConnectionDouble([pg._migration_hashes(), None])
    if failure == 'batch':
        connection.fail_query = pg.CORE_INSERT
    if failure == 'completion':
        connection.fail_query = pg.COMPLETED_INSERT
    if failure == 'splits':
        partitions = {'train': 0, 'validation': 0, 'test': 0}
    if failure == 'source_exit':
        original = pg.verified_source
        @contextmanager
        def late_failure(*args):
            with original(*args) as stream:
                yield stream
            raise IntegrityError('consumed source changed')
        monkeypatch.setattr(pg, 'verified_source', late_failure)
    if failure == 'code_change':
        identities = iter(['a' * 64, 'b' * 64])
        monkeypatch.setattr(pg, 'persistence_identity', lambda: next(identities))
    with pytest.raises((IntegrityError, RuntimeError)):
        pg.load_artifact(connection, source, contract=contract, expected_partitions=partitions, batch_size=1)
    assert connection.commits == 0 and connection.rollbacks == 1
    if failure != 'completion':
        assert not any(query == pg.COMPLETED_INSERT for query, _ in connection.calls)


def test_conflicting_existing_load_fails_without_overwrite(postgres_artifact):
    source, contract, partitions = postgres_artifact()
    connection = ConnectionDouble([pg._migration_hashes(), ('old-version', 'wrong-hash')])
    with pytest.raises(IntegrityError, match='different implementation'):
        pg.load_artifact(connection, source, contract=contract, expected_partitions=partitions)
    assert not any(q.startswith(('INSERT', 'UPDATE', 'DELETE')) for q, _ in connection.calls)
    assert connection.rollbacks == 1


@pytest.mark.parametrize('orphan_lineage', [False, True])
def test_server_cursor_readback_contract(postgres_artifact, orphan_lineage):
    source, contract, _ = postgres_artifact()
    rows, examples, expected = fixture_values(source, contract)
    core_rows, enhanced_rows = [], []
    for example in examples:
        lineage, core, enhanced = pg.example_values(example)
        core_rows.append((*core, lineage[-1]))
        enhanced_rows.append((*core, *enhanced[1:]))
    streams = iter([[pg.canonical_values(row) for row in rows], core_rows, enhanced_rows])
    connection = ConnectionDouble([(len(examples) + int(orphan_lineage),)])
    @contextmanager
    def cursor(name):
        assert name == 'stage4d_readback'
        class Rows:
            def execute(self, query, params):
                assert query in (pg.CANONICAL_SELECT, pg.CORE_SELECT, pg.ENHANCED_SELECT)
                assert params == (rows[0].artifact_id,)
            def __iter__(self):
                return iter(next(streams))
        yield Rows()
    connection.cursor = cursor
    if orphan_lineage:
        with pytest.raises(IntegrityError, match='incomplete examples'):
            pg.readback(connection, rows[0].artifact_id)
    else:
        assert pg.readback(connection, rows[0].artifact_id) == expected


@pytest.mark.parametrize('corruption', ['metadata', 'contents', 'completion'])
def test_inconsistent_reload_is_not_accepted(postgres_artifact, monkeypatch, corruption):
    source, contract, splits = postgres_artifact()
    _, _, report = fixture_values(source, contract)
    monkeypatch.setattr(pg, 'readback', lambda *args: report)
    first = ConnectionDouble([pg._migration_hashes(), None])
    pg.load_artifact(first, source, contract=contract, expected_partitions=splits)
    metadata = next(p for q, p in first.calls if q == pg.ARTIFACT_INSERT)
    completion = next(p[1:] for q, p in first.calls if q == pg.COMPLETED_INSERT)
    if corruption == 'metadata':
        metadata = (*metadata[:-1], 'changed licence')
    elif corruption == 'contents':
        monkeypatch.setattr(pg, 'readback', lambda *args: {**report, 'core_sha256': '0' * 64})
    else:
        completion = (*completion[:-1], '0' * 64)
    repeated = ConnectionDouble([pg._migration_hashes(), completion, metadata])
    with pytest.raises(IntegrityError):
        pg.load_artifact(repeated, source, contract=contract, expected_partitions=splits)
    assert repeated.rollbacks == 1 and repeated.commits == 0
    assert not any(q.startswith(('INSERT', 'UPDATE', 'DELETE')) for q, _ in repeated.calls)


def test_regression_after_written_batch_requests_rollback(postgres_artifact):
    source, contract, splits = postgres_artifact([
        ['1', 'TRANSFER', '1', 'A', '0', '1', 'B', '0', '1', '0'],
        ['0', 'TRANSFER', '1', 'A', '0', '1', 'B', '0', '1', '0'],
    ])
    connection = ConnectionDouble([pg._migration_hashes(), None])
    with pytest.raises(ValueError, match='chronological regression'):
        pg.load_artifact(connection, source, contract=contract, expected_partitions=splits, batch_size=1)
    assert connection.rollbacks == 1 and connection.commits == 0
    assert any(q == pg.CANONICAL_INSERT for q, _ in connection.calls)
    assert not any(q == pg.COMPLETED_INSERT for q, _ in connection.calls)


def test_connect_and_cli_do_not_expose_configuration(monkeypatch, capsys):
    monkeypatch.delenv('TRANSACTIONSHIELD_DATABASE_DSN', raising=False)
    with pytest.raises(RuntimeError, match='explicitly'):
        pg.connect()
    sensitive = 'unit-test-private-marker'
    def broken(*args, **kwargs):
        raise RuntimeError(sensitive)
    monkeypatch.setitem(sys.modules, 'psycopg', SimpleNamespace(connect=broken))
    with pytest.raises(RuntimeError) as caught:
        pg.connect(sensitive)
    assert sensitive not in str(caught.value)
    assert caught.value.__suppress_context__
    monkeypatch.setattr(pg, 'connect', broken)
    assert pg.main(['schema']) == 1
    output = capsys.readouterr()
    assert sensitive not in output.out + output.err
    assert 'failed' in output.err
