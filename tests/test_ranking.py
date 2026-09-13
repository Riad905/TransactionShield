"""Hand-calculated ranking metrics; no changes to the frozen experiment."""

import pytest

np = pytest.importorskip('numpy')
pytest.importorskip('sklearn')
from transactionshield.modelling import review_budget_metrics


def test_fixed_budgets_and_hand_calculated_metrics():
    labels = np.zeros(200, dtype=int)
    labels[:10] = 1
    rows = review_budget_metrics(labels, np.linspace(1, 0, 200))
    assert [r['budget_fraction'] for r in rows] == [0.005, 0.01, 0.02, 0.05, 0.1]
    assert [r['reviewed'] for r in rows] == [1, 2, 4, 10, 20]
    assert [r['fraud_captured'] for r in rows] == [1, 2, 4, 10, 10]
    assert [r['precision'] for r in rows] == [1, 1, 1, 1, 0.5]
    assert [r['recall'] for r in rows] == [0.1, 0.2, 0.4, 1, 1]
    assert [r['lift_over_prevalence'] for r in rows] == [20, 20, 20, 20, 10]


def test_rounding_and_score_ties_use_input_order_not_labels():
    labels = np.array([0, 1, 1])
    scores = np.ones(3) / 2
    first = review_budget_metrics(labels, scores)
    assert all(r['reviewed'] == 1 and r['fraud_captured'] == 0 for r in first)
    assert first == review_budget_metrics(labels, scores)
    assert np.array_equal(labels, [0, 1, 1]) and np.array_equal(scores, [0.5] * 3)
    # Reversing labels does not move the selected tied position.
    assert all(r['fraud_captured'] == 1 for r in review_budget_metrics(labels[::-1], scores))


def test_no_fraud_has_undefined_recall_and_lift():
    assert all(r['precision'] == 0 and r['recall'] is None and r['lift_over_prevalence'] is None
               for r in review_budget_metrics([0, 0], [0.7, 0.2]))


@pytest.mark.parametrize('labels,scores', [([], []), ([0], []), ([2], [0.1]),
    ([0], [float('nan')]), ([1], [float('inf')]), ([1], [-0.1]), ([1], [1.1]),
    ([[1]], [[0.5]])])
def test_invalid_ranking_inputs_are_rejected(labels, scores):
    with pytest.raises(ValueError):
        review_budget_metrics(labels, scores)
