"""Verified Decimal features -> explicit, lossy estimator-only float64 boundary."""

import hashlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from transactionshield.canonical import iter_canonical_records
from transactionshield.contracts import evaluation_partition
from transactionshield.feature_validation import APPROVED_PARTITION_COUNTS, _diagnostic_bytes
from transactionshield.features import CORE_FEATURE_NAMES, ENHANCED_ADDITIONAL_NAMES, iter_feature_examples
from transactionshield.validation import APPROVED_ARTIFACT, IntegrityError, Reconciliation, verified_source

ALL_FEATURES = (*CORE_FEATURE_NAMES, *ENHANCED_ADDITIONAL_NAMES)
APPROVED_HASHES = (
    '256bdaa32d81e2f6c2c3ddd1780aee5b37695951d9fa63eef5e805c3952c4df5',
    '011f5c488f9a1ed5cc1669c1d6023e719abcff2a873e30703e6dd7fc688dafd7',
)


@dataclass
class ModelData:
    features: np.ndarray
    labels: np.ndarray
    steps: np.ndarray

    def partition(self, name):
        masks = split_masks(self.steps)
        return self.features[masks[name]], self.labels[masks[name]]


def split_masks(steps):
    steps = np.asarray(steps)
    if steps.ndim != 1 or steps.dtype.kind not in 'iu' or np.any((steps < 0) | (steps > 143)):
        raise ValueError('Expected integer steps within the frozen horizon')
    if np.any(steps[1:] < steps[:-1]):
        raise ValueError('Chronological regression; never reorder silently')
    return {'train': steps <= 95, 'validation': (steps >= 96) & (steps <= 119), 'test': steps >= 120}


def tier_matrix(values, tier, names=ALL_FEATURES):
    if tuple(names) != ALL_FEATURES or values.ndim != 2 or values.shape[1] != len(ALL_FEATURES):
        raise ValueError('Exact approved feature names and order required')
    if tier not in ('core', 'enhanced'):
        raise ValueError('Unknown feature tier')
    return values[:, :len(CORE_FEATURE_NAMES)] if tier == 'core' else values


def build_model_data(source, *, contract=APPROVED_ARTIFACT, expected_partitions=None, expected_hashes=APPROVED_HASHES):
    """No arrays leave this function until source and exact feature gates pass.

    Alternate contracts/hashes are for fixtures, not exposed by the CLI.
    Labels remain separate from the narrow behavioural engine and feature matrix.
    """
    expected_partitions = APPROVED_PARTITION_COUNTS if expected_partitions is None else expected_partitions
    count = sum(expected_partitions.values())
    values = np.empty((count, len(ALL_FEATURES)), dtype=np.float64)
    labels = np.empty(count, dtype=np.int8)
    steps = np.empty(count, dtype=np.int16)
    reconciliation = Reconciliation()
    digests = (hashlib.sha256(), hashlib.sha256())
    partitions = Counter()
    current_label = None
    emitted = 0
    with verified_source(Path(source).resolve(strict=True), contract) as stream:
        def canonical_rows():
            nonlocal current_label
            for row in iter_canonical_records(stream, contract.sha256):
                reconciliation.observe(row)
                current_label = row.is_fraud  # Target side channel, never an engine input.
                yield row
        for example in iter_feature_examples(canonical_rows(), enhanced=True):
            if emitted >= count:
                raise IntegrityError('Too many eligible model examples')
            for digest, enhanced in zip(digests, (False, True), strict=True):
                digest.update(_diagnostic_bytes(example, enhanced=enhanced))
            exact = [getattr(example.core, name) for name in CORE_FEATURE_NAMES]
            exact.extend(getattr(example.enhanced, name) for name in ENHANCED_ADDITIONAL_NAMES)
            # Conversion is only here, AFTER exact feature construction/hashing.
            values[emitted] = [np.nan if value is None else float(value) for value in exact]
            labels[emitted] = current_label
            steps[emitted] = example.lineage.step
            partitions[evaluation_partition(example.lineage.step)] += 1
            emitted += 1
    reconciliation.verify(contract)
    hashes = tuple(digest.hexdigest() for digest in digests)
    observed_partitions = {name: partitions[name] for name in expected_partitions}
    if emitted != count or observed_partitions != expected_partitions:
        raise IntegrityError('Model population/splits differ from approved contract')
    if expected_hashes is not None and hashes != tuple(expected_hashes):
        raise IntegrityError('Exact features differ from approved Stage 4C hashes')
    if np.isinf(values).any():
        raise IntegrityError('Estimator float conversion overflowed')
    nulls = np.isnan(values).sum(axis=0)
    if any(nulls[i] for i, name in enumerate(ALL_FEATURES) if not name.endswith(('mean', 'max'))):
        raise IntegrityError('Unexpected null model input')
    split_masks(steps)
    report = {'source_sha256': contract.sha256, 'source_rows': reconciliation.row_count,
              'examples': emitted, 'partitions': observed_partitions,
              'core_sha256': hashes[0], 'enhanced_sha256': hashes[1],
              'null_counts': dict(zip(ALL_FEATURES, map(int, nulls), strict=True)),
              'feature_names': list(ALL_FEATURES), 'matrix_bytes': int(values.nbytes),
              'estimator_dtype': 'float64 (lossy conversion only at model boundary)'}
    return ModelData(values, labels, steps), report
