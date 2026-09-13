"""Small, explicitly alternate artifact for Stage 4D tests; never the real data."""

import csv
import hashlib
import io
import tempfile
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from transactionshield.contracts import evaluation_partition
from transactionshield.ingestion import MOMTSIM_PAPER_DATASET_V1_COLUMNS
from transactionshield.validation import APPROVED_ARTIFACT


@pytest.fixture
def postgres_artifact():
    parent = Path(__file__).resolve().parents[1] / 'data' / 'interim'
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='stage4d-test-', dir=parent) as directory:
        def create(rows=None):
            if rows is None:
                rows = [[str(step), kind, str(amount), ' 001 ', '-10.000', '-11', "B';--", '0', '1', label]
                        for step, kind, amount, label in [
                            (0, 'TRANSFER', 1, '1'), (0, 'PAYMENT', 2, '0'),
                            (95, 'TRANSFER', 3, '0'), (96, 'TRANSFER', 4, '0'),
                            (119, 'PAYMENT', 5, '0'), (120, 'TRANSFER', 6, '0')]]
            text = io.StringIO(newline='')
            writer = csv.writer(text, lineterminator='\n')
            writer.writerow(MOMTSIM_PAPER_DATASET_V1_COLUMNS)
            writer.writerows(rows)
            payload = text.getvalue().encode('utf-8')
            source = Path(directory) / APPROVED_ARTIFACT.filename
            source.write_bytes(payload)
            labels = Counter(row[-1] for row in rows)
            types = Counter(row[1] for row in rows)
            splits = Counter(evaluation_partition(int(row[0])) for row in rows if row[1] == 'TRANSFER')
            contract = replace(APPROVED_ARTIFACT, byte_size=len(payload),
                               sha256=hashlib.sha256(payload).hexdigest(), row_count=len(rows),
                               legitimate_count=labels['0'], fraud_count=labels['1'],
                               transaction_type_counts=tuple(sorted(types.items())),
                               step_min=min(int(row[0]) for row in rows), step_max=max(int(row[0]) for row in rows))
            return source, contract, {name: splits[name] for name in ('train', 'validation', 'test')}
        yield create
