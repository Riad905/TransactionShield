"""Real estimators on small fixtures; no synthetic augmentation of source data."""

import inspect
import hashlib
import json
import tempfile
from pathlib import Path

import pytest
np = pytest.importorskip('numpy', reason='Install the modelling extra for estimator tests')
pytest.importorskip('sklearn', reason='Install the modelling extra for estimator tests')
from threadpoolctl import threadpool_limits

from transactionshield import modelling as model
from transactionshield.model_data import ALL_FEATURES, ModelData, build_model_data, split_masks, tier_matrix
from transactionshield.validation import IntegrityError


def sample(seed=1, count=180):
    rng = np.random.default_rng(seed)
    values = rng.uniform(0, 10, (count, 11))
    values[::7, 4:6] = np.nan
    labels = (values[:, 0] + values[:, 10] > 11).astype(int)
    return values, labels


def test_exact_feature_allowlist_and_tiers():
    values, _ = sample()
    assert tier_matrix(values, 'core').shape[1] == 9
    assert tier_matrix(values, 'enhanced').shape[1] == 11
    for forbidden in ('is_fraud', 'step', 'transaction_id', 'source_row_number', 'initiator_balance_after'):
        with pytest.raises(ValueError):
            tier_matrix(values, 'core', names=(*ALL_FEATURES[:-1], forbidden))
    changed = values.copy()
    changed[:, 9:] = -100
    np.testing.assert_array_equal(tier_matrix(values, 'core'), tier_matrix(changed, 'core'))


def test_frozen_chronological_masks():
    masks = split_masks(np.array([0, 95, 96, 119, 120, 143]))
    assert {name: np.flatnonzero(mask).tolist() for name, mask in masks.items()} == {
        'train': [0, 1], 'validation': [2, 3], 'test': [4, 5]}
    with pytest.raises(ValueError, match='regression'):
        split_masks(np.array([96, 95]))
    with pytest.raises(ValueError):
        split_masks(np.array([144]))


def test_source_features_are_validated_before_model_arrays_escape(postgres_artifact):
    source, contract, splits = postgres_artifact()
    data, gate = build_model_data(source, contract=contract, expected_partitions=splits, expected_hashes=None)
    assert gate['examples'] == 4 and gate['source_rows'] == 6
    assert data.steps.tolist() == [0, 95, 96, 120]
    assert data.labels.tolist() == [1, 0, 0, 0]
    assert data.features[:, 1].tolist() == [0, 2, 3, 5]
    assert np.isnan(data.features[0, 4:6]).all()
    assert data.features[1, 4] == 1.5
    with pytest.raises(IntegrityError, match='Stage 4C hashes'):
        build_model_data(source, contract=contract, expected_partitions=splits)


def test_preprocessing_fits_train_only():
    train, labels = sample()
    fitted = model.make_model('logistic')
    with threadpool_limits(limits=1):
        fitted.fit(train, labels)
        expected_medians = np.nanmedian(train, axis=0)
        np.testing.assert_allclose(fitted[0].statistics_, expected_medians)
        expected_means = np.where(np.isnan(train), expected_medians, train).mean(axis=0)
        np.testing.assert_allclose(fitted[1].mean_, expected_means)
        fitted.predict_proba(np.full((10, 11), 999999.0))
        np.testing.assert_allclose(fitted[1].mean_, expected_means)
    assert model.make_model('boosting').early_stopping is False


def test_metrics_against_hand_calculation():
    result = model.metrics(np.array([0, 0, 1, 1]), np.array([0.1, 0.7, 0.4, 0.9]), 0.5)
    assert result['confusion_matrix'] == [[1, 1], [1, 1]]
    assert result['precision'] == result['recall'] == result['f1'] == 0.5
    assert result['prevalence'] == 0.5
    assert result['roc_auc'] == 0.75
    assert result['average_precision'] == pytest.approx(5 / 6)


def test_threshold_uses_validation_and_is_not_assumed_half():
    threshold = model.select_threshold(np.array([0, 0, 1, 1]), np.array([0.1, 0.2, 0.3, 0.4]))
    assert threshold == 0.3
    assert tuple(inspect.signature(model.fit_and_select).parameters) == ('train', 'validation')
    assert tuple(inspect.signature(model.select_threshold).parameters) == ('validation_labels', 'validation_scores')


def test_real_estimators_repeat_deterministically_and_freeze_before_test():
    train, validation, test = sample(1), sample(2), sample(3)
    with threadpool_limits(limits=1):
        fitted, records, winner = model.fit_and_select(train, validation)
        repeated, repeated_records, repeated_winner = model.fit_and_select(train, validation)
        assert records == repeated_records and winner == repeated_winner
        first, _ = model.evaluate_test(fitted, test)
        second, _ = model.evaluate_test(repeated, test)
        assert first == second
        frozen_thresholds = {name: value[2] for name, value in fitted.items()}
        model.evaluate_test(fitted, (test[0], 1 - test[1]))
        assert frozen_thresholds == {name: value[2] for name, value in fitted.items()}


def test_error_samples_have_no_identifiers_and_slices_keep_counts():
    x, y = sample()
    scores = np.linspace(0.01, 0.99, len(y))
    report = model.error_analysis(y, scores, x, 0.5, np.array([2.5, 5, 7.5]))
    assert sum(s['count'] for s in report['test_amount_slices']) == len(y)
    for examples in report['representatives_without_identifiers'].values():
        for example in examples:
            assert set(example) == {'label', 'score', 'amount', 'prior_outgoing_count'}


def test_run_rejects_output_outside_ignored_artifacts():
    with pytest.raises(ValueError, match='artifacts'):
        model.run('unused.csv', 'docs/should-not-exist')


def test_complete_fixture_run_checksum_is_actual_file_bytes(monkeypatch):
    partitions = [sample(seed, 180) for seed in (1, 2, 3)]
    data = ModelData(np.vstack([p[0] for p in partitions]), np.concatenate([p[1] for p in partitions]),
                     np.repeat([0, 96, 120], 180))
    # Only substitute the large input artifact; fitting/selection/evaluation are real.
    monkeypatch.setattr(model, 'build_model_data', lambda source: (data, {'fixture': True}))
    parent = model.REPOSITORY_ROOT / 'artifacts'
    parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='modelling-test-', dir=parent) as directory:
        output = Path(directory) / 'run'
        result = model.run('controlled-fixture', output)
        payload = (output / 'metrics.json').read_bytes()
        runtime = json.loads((output / 'runtime.json').read_text())
        assert b'\r\n' not in payload
        assert runtime['metrics_sha256'] == hashlib.sha256(payload).hexdigest()
        frozen = json.loads((output / 'selection.json').read_text())
        assert frozen['selected_by_validation_ap'] == result['selected_by_validation_ap']
        assert all('test' not in entry for entry in frozen['experiments'].values())
