"""Small chronological modelling experiment; no database or serving claims."""

import argparse
import hashlib
import json
import platform
import time
import warnings
from pathlib import Path

import numpy as np
import scipy
import sklearn
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.exceptions import ConvergenceWarning
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, brier_score_loss, confusion_matrix,
                             f1_score, precision_recall_curve, precision_score, recall_score, roc_auc_score)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from transactionshield.features import CORE_FEATURE_NAMES
from transactionshield.model_data import ALL_FEATURES, build_model_data, tier_matrix
from transactionshield.pipeline import REPOSITORY_ROOT, code_identity
from transactionshield.validation import IntegrityError

SEED = 904
REVIEW_BUDGET_BASIS_POINTS = (50, 100, 200, 500, 1000)


def review_budget_metrics(labels, scores):
    """Descriptive fixed capacities, never a budget/threshold selection routine.

    Ceil(n * basis_points / 10000) determines capacity. Stable input order breaks
    score ties without consulting labels; replay order is not a model feature.
    Recall and lift are undefined (None) when there are no positive labels.
    """
    labels, scores = np.asarray(labels), np.asarray(scores, dtype=float)
    if (labels.ndim != 1 or scores.shape != labels.shape or not len(labels)
            or not np.isin(labels, [0, 1]).all() or not np.isfinite(scores).all()
            or np.any((scores < 0) | (scores > 1))):
        raise ValueError('Expected nonempty aligned binary labels and finite probabilities')
    ranked = np.argsort(-scores, kind='stable')
    cumulative = np.cumsum(labels[ranked], dtype=np.int64)
    total_fraud = int(cumulative[-1])
    prevalence = total_fraud / len(labels)
    result = []
    for budget in REVIEW_BUDGET_BASIS_POINTS:
        reviewed = (len(labels) * budget + 9999) // 10000
        captured = int(cumulative[reviewed - 1])
        precision = captured / reviewed
        result.append({'budget_fraction': budget / 10000, 'reviewed': reviewed,
                       'fraud_captured': captured, 'precision': precision,
                       'recall': captured / total_fraud if total_fraud else None,
                       'lift_over_prevalence': precision / prevalence if total_fraud else None})
    return result


def select_threshold(validation_labels, validation_scores):
    """Max validation F1; ties choose the highest threshold (fewer alerts)."""
    precision, recall, thresholds = precision_recall_curve(validation_labels, validation_scores)
    f1 = np.divide(2 * precision[:-1] * recall[:-1], precision[:-1] + recall[:-1],
                   out=np.zeros_like(thresholds), where=(precision[:-1] + recall[:-1]) != 0)
    return float(thresholds[np.flatnonzero(f1 == f1.max())[-1]])


def metrics(labels, scores, threshold):
    predictions = scores >= threshold
    return {'count': len(labels), 'prevalence': float(np.mean(labels)),
            'roc_auc': float(roc_auc_score(labels, scores)) if len(np.unique(labels)) == 2 else None,
            'average_precision': float(average_precision_score(labels, scores)) if np.any(labels) else None,
            'precision': float(precision_score(labels, predictions, zero_division=0)),
            'recall': float(recall_score(labels, predictions, zero_division=0)),
            'f1': float(f1_score(labels, predictions, zero_division=0)),
            'confusion_matrix': confusion_matrix(labels, predictions, labels=[0, 1]).tolist(),
            'alert_rate': float(np.mean(predictions)), 'brier_score': float(brier_score_loss(labels, scores))}


def make_model(kind):
    if kind == 'baseline':
        return DummyClassifier(strategy='prior', random_state=SEED)
    if kind == 'logistic':
        return make_pipeline(SimpleImputer(strategy='median', keep_empty_features=True), StandardScaler(),
                             LogisticRegression(C=1.0, max_iter=1000, solver='lbfgs', random_state=SEED))
    if kind == 'boosting':
        return HistGradientBoostingClassifier(max_iter=100, max_leaf_nodes=15, min_samples_leaf=50,
                                              learning_rate=0.1, l2_regularization=1.0,
                                              early_stopping=False, random_state=SEED)
    raise ValueError('Unknown model')


def fit_and_select(train, validation):
    """This API cannot see the test partition. All decisions finish here."""
    x_train, y_train = train
    x_validation, y_validation = validation
    fitted, records = {}, {}
    specs = [('baseline', 'core', 'baseline'), ('core_logistic', 'core', 'logistic'),
             ('core_boosting', 'core', 'boosting'), ('enhanced_logistic', 'enhanced', 'logistic'),
             ('enhanced_boosting', 'enhanced', 'boosting')]
    for name, tier, kind in specs:
        model = make_model(kind)
        with warnings.catch_warnings():
            warnings.simplefilter('error', ConvergenceWarning)
            model.fit(tier_matrix(x_train, tier), y_train)
        scores = model.predict_proba(tier_matrix(x_validation, tier))[:, 1]
        threshold = select_threshold(y_validation, scores)
        fitted[name] = (model, tier, threshold)
        records[name] = {'tier': tier, 'threshold': threshold,
                         'model_parameters': (model[-1] if kind == 'logistic' else model).get_params(),
                         'features': list(CORE_FEATURE_NAMES if tier == 'core' else ALL_FEATURES),
                         'validation': metrics(y_validation, scores, threshold),
                         'validation_at_0_5': metrics(y_validation, scores, 0.5)}
    winner = max(records, key=lambda name: records[name]['validation']['average_precision'])
    return fitted, records, winner


def explain(fitted, validation):
    x_validation, y_validation = validation
    chosen = np.random.default_rng(SEED).choice(len(y_validation), min(10000, len(y_validation)), replace=False)
    result = {}
    for name, (model, tier, _) in fitted.items():
        names = CORE_FEATURE_NAMES if tier == 'core' else ALL_FEATURES
        if name.endswith('logistic'):
            result[name] = {'standardized_coefficients': dict(zip(names, map(float, model[-1].coef_[0]), strict=True))}
        elif name.endswith('boosting'):
            importance = permutation_importance(model, tier_matrix(x_validation[chosen], tier), y_validation[chosen],
                                                scoring='average_precision', n_repeats=3, random_state=SEED, n_jobs=1)
            result[name] = {'validation_permutation_ap_decrease': dict(zip(names, map(float, importance.importances_mean), strict=True)),
                            'std': dict(zip(names, map(float, importance.importances_std), strict=True)),
                            'sample_count': len(chosen)}
    return result


def error_analysis(labels, scores, features, threshold, amount_edges):
    predicted = scores >= threshold
    groups = {'false_positive': (labels == 0) & predicted,
              'false_negative': (labels == 1) & ~predicted,
              'correct_fraud': (labels == 1) & predicted,
              'high_confidence_wrong': (labels != predicted)}
    examples = {}
    for name, mask in groups.items():
        indices = np.flatnonzero(mask)
        confidence = (1 - scores[indices]) if name == 'false_negative' else scores[indices]
        if name == 'high_confidence_wrong':
            confidence = np.maximum(scores[indices], 1 - scores[indices])
        ranked = indices[np.argsort(-confidence, kind='stable')[:3]]
        examples[name] = [{'label': int(labels[i]), 'score': float(scores[i]),
                           'amount': float(features[i, 0]), 'prior_outgoing_count': int(features[i, 1])} for i in ranked]
    slices = []
    bins = np.searchsorted(amount_edges, features[:, 0], side='right')
    for index in range(len(amount_edges) + 1):
        mask = bins == index
        if np.any(mask):
            slices.append({'train_amount_quartile': index + 1, **metrics(labels[mask], scores[mask], threshold)})
    return {'representatives_without_identifiers': examples, 'amount_slice_edges_from_train': amount_edges.tolist(),
            'test_amount_slices': slices}


def evaluate_test(fitted, test):
    x_test, y_test = test
    records, probabilities = {}, {}
    for name, (model, tier, threshold) in fitted.items():
        probabilities[name] = model.predict_proba(tier_matrix(x_test, tier))[:, 1]
        records[name] = {'test': metrics(y_test, probabilities[name], threshold),
                         'test_at_0_5': metrics(y_test, probabilities[name], 0.5)}
    return records, probabilities


def peak_working_set():
    if platform.system() != 'Windows':
        return None
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ('peak', 'working', 'peak_paged', 'paged', 'peak_nonpaged',
                                               'nonpaged', 'pagefile', 'peak_pagefile')]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.windll.kernel32
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    memory = ctypes.windll.psapi.GetProcessMemoryInfo
    memory.argtypes = (wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD)
    return int(counters.peak) if memory(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb) else None


def run(source, destination):
    destination = Path(destination).resolve()
    if not destination.is_relative_to((REPOSITORY_ROOT / 'artifacts').resolve()) or destination.exists():
        raise ValueError('Choose a new run directory under ignored artifacts/')
    identity = code_identity()
    started = time.perf_counter()
    data, gate = build_model_data(source)
    extraction_seconds = time.perf_counter() - started
    print('Source and exact feature hashes verified; training begins.', flush=True)
    train, validation = data.partition('train'), data.partition('validation')
    amount_edges = np.quantile(train[0][:, 0], [0.25, 0.5, 0.75])
    with threadpool_limits(limits=1):
        fitted, records, winner = fit_and_select(train, validation)
        interpretation = explain(fitted, validation)
        if identity != code_identity():
            raise IntegrityError('Implementation changed before final evaluation')
        # Persist the frozen selection BEFORE any test-label evaluation.
        destination.mkdir(parents=True)
        frozen = {'selected_by_validation_ap': winner, 'experiments': records,
                  'seed': SEED, 'amount_edges_from_train': amount_edges.tolist(), 'code': identity}
        (destination / 'selection.json').write_text(json.dumps(frozen, indent=2), encoding='utf-8', newline='\n')
        print('Validation selection frozen; final test evaluation begins.', flush=True)
        test = data.partition('test')
        test_records, scores = evaluate_test(fitted, test)
        for name in records:
            records[name].update(test_records[name])
        errors = error_analysis(test[1], scores[winner], test[0], fitted[winner][2], amount_edges)
        # The finalisation request freezes Enhanced boosting, not a new test winner.
        ranking = review_budget_metrics(test[1], scores['enhanced_boosting'])
    if identity != code_identity():
        raise IntegrityError('Implementation changed during experiment')
    result = {'input_gate': gate, 'seed': SEED, 'threads': 1, 'selected_by_validation_ap': winner,
              'threshold_policy': 'maximum validation F1; highest threshold breaks ties; not an operational cost optimum',
              'experiments': records, 'explainability': interpretation, 'error_analysis': errors,
              'posthoc_review_budgets': {'model': 'enhanced_boosting',
                                       'policy': 'fixed budgets; ceil capacity; stable replay-order score ties; no tuning',
                                       'results': ranking},
              'versions': {'python': platform.python_version(), 'sklearn': sklearn.__version__,
                           'numpy': np.__version__, 'scipy': scipy.__version__}, 'code': identity}
    payload = json.dumps(result, indent=2, allow_nan=False)
    (destination / 'metrics.json').write_text(payload, encoding='utf-8', newline='\n')
    runtime = {'source_feature_seconds': extraction_seconds, 'total_seconds': time.perf_counter() - started,
               'peak_process_working_set_bytes': peak_working_set(), 'metrics_sha256': hashlib.sha256(payload.encode()).hexdigest()}
    (destination / 'runtime.json').write_text(json.dumps(runtime, indent=2), encoding='utf-8', newline='\n')
    print(json.dumps({'selected_model': winner, **runtime}, indent=2))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    run(args.source, args.output)


if __name__ == '__main__':
    main()
