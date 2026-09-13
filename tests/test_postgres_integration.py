"""Real PostgreSQL only. No configured test server means explicit skips."""

import os
from decimal import Decimal

import pytest

from transactionshield import postgres as pg
from transactionshield.features import CORE_FEATURE_NAMES, historical_amount_mean
from transactionshield.validation import IntegrityError

pytestmark = pytest.mark.postgres


@pytest.fixture
def database():
    dsn = os.environ.get('TRANSACTIONSHIELD_TEST_DATABASE_DSN')
    if not dsn:
        pytest.skip('NOT RUN: no explicit disposable PostgreSQL test database configured')
    pytest.importorskip('psycopg', reason='NOT RUN: optional PostgreSQL driver is unavailable')
    with pg.connect(dsn) as connection:
        # Never adopt or clear a user's existing application schema.
        if not connection.info.dbname.startswith('transactionshield_test'):
            pytest.fail('Integration tests require a database name starting transactionshield_test')
        if connection.execute('SELECT to_regnamespace(%s)', ('transactionshield',)).fetchone()[0] is not None:
            pytest.fail('Integration tests require an absent transactionshield schema; nothing was removed')
        pg.apply_schema(connection)
        try:
            yield connection
        finally:
            # Only the fixed schema created above, in the explicitly opted-in test DB.
            connection.execute('DROP SCHEMA transactionshield CASCADE')


def test_real_schema_and_numeric_round_trip(database):
    pg.apply_schema(database)
    columns = database.execute(
        'SELECT column_name FROM information_schema.columns '
        'WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position',
        ('transactionshield', 'core_predictors')).fetchall()
    assert tuple(row[0] for row in columns) == CORE_FEATURE_NAMES
    values = [Decimal('1.20'), Decimal('123456789012345678901234567890.123456789'),
              Decimal('-10.000'), Decimal(0), historical_amount_mean(Decimal(1), 3), None]
    # An actual NUMERIC column, not just driver-side parameter adaptation.
    with database.transaction():
        database.execute('CREATE TEMP TABLE decimal_roundtrip (position INTEGER PRIMARY KEY, value NUMERIC) ON COMMIT DROP')
        for position, value in enumerate(values):
            database.execute('INSERT INTO decimal_roundtrip VALUES (%s, %s)', (position, value))
        actual = database.execute('SELECT value FROM decimal_roundtrip ORDER BY position').fetchall()
        assert [row[0] for row in actual] == values
        assert all(value is None or isinstance(value, Decimal) for value, in actual)


def test_real_load_reload_and_tier_separation(database, postgres_artifact):
    source, contract, splits = postgres_artifact()
    first = pg.load_artifact(database, source, contract=contract, expected_partitions=splits, batch_size=2)
    second = pg.load_artifact(database, source, contract=contract, expected_partitions=splits, batch_size=1)
    assert second == {**first, 'status': 'verified_existing'}
    assert first['canonical_count'] == 6 and first['feature_count'] == first['enhanced_count'] == 4
    assert first['partitions'] == {'train': 2, 'validation': 1, 'test': 1}
    rows = database.execute(pg.CORE_SELECT, (first['artifact_id'],)).fetchall()
    assert [row[2] for row in rows] == [0, 2, 3, 5]
    assert rows[0][5:7] == (None, None)
    assert rows[1][5] == Decimal('1.5')
    assert database.execute('SELECT DISTINCT initiator_balance_before FROM transactionshield.enhanced_feature').fetchall() == [(Decimal('-10.000'),)]


def test_real_late_failure_rolls_back_all_tables(database, postgres_artifact, monkeypatch):
    source, contract, splits = postgres_artifact()
    original = pg.BatchWriter.flush
    def fail_after_write(writer):
        original(writer)
        raise RuntimeError('injected failure after database batches')
    monkeypatch.setattr(pg.BatchWriter, 'flush', fail_after_write)
    with pytest.raises(RuntimeError, match='injected'):
        pg.load_artifact(database, source, contract=contract, expected_partitions=splits, batch_size=1)
    assert database.execute('SELECT count(*) FROM transactionshield.dataset_artifact').fetchone() == (0,)
    assert database.execute('SELECT count(*) FROM transactionshield.canonical_transaction').fetchone() == (0,)
    assert database.execute('SELECT count(*) FROM transactionshield.core_feature').fetchone() == (0,)
    assert database.execute('SELECT count(*) FROM transactionshield.completed_load').fetchone() == (0,)


def test_real_duplicate_and_integrity_constraints(database, postgres_artifact):
    import psycopg
    source, contract, splits = postgres_artifact()
    pg.load_artifact(database, source, contract=contract, expected_partitions=splits)
    with pytest.raises(psycopg.errors.UniqueViolation), database.transaction():
        database.execute('INSERT INTO transactionshield.core_feature SELECT * FROM transactionshield.core_feature')
    for query in (
        "UPDATE transactionshield.feature_lineage SET partition = 'test' WHERE step = 0",
        "UPDATE transactionshield.feature_lineage SET transaction_type = 'PAYMENT'",
        "UPDATE transactionshield.core_feature SET amount = 'NaN'::numeric",
        'UPDATE transactionshield.core_feature SET initiator_prior_outgoing_amount_mean = NULL WHERE initiator_prior_outgoing_count > 0',
        "UPDATE transactionshield.enhanced_feature SET initiator_balance_before = 'Infinity'::numeric",
    ):
        with pytest.raises(psycopg.errors.CheckViolation), database.transaction():
            database.execute(query)
    # A real non-transfer canonical key cannot acquire feature metadata.
    with pytest.raises(psycopg.errors.ForeignKeyViolation), database.transaction():
        database.execute("INSERT INTO transactionshield.feature_lineage SELECT transaction_id, artifact_id, step, 'TRANSFER', 'train' FROM transactionshield.canonical_transaction WHERE transaction_type = 'PAYMENT' AND step = 0")


def test_real_modified_contents_are_not_silently_overwritten(database, postgres_artifact):
    source, contract, splits = postgres_artifact()
    pg.load_artifact(database, source, contract=contract, expected_partitions=splits)
    database.execute('UPDATE transactionshield.core_feature SET amount = amount + 1')
    before = database.execute('SELECT sum(amount) FROM transactionshield.core_feature').fetchone()
    with pytest.raises(IntegrityError, match='read-back'):
        pg.load_artifact(database, source, contract=contract, expected_partitions=splits)
    assert database.execute('SELECT sum(amount) FROM transactionshield.core_feature').fetchone() == before
