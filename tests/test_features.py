from dataclasses import FrozenInstanceError, fields, replace
from decimal import Context, Decimal, Inexact, ROUND_DOWN, ROUND_HALF_EVEN, localcontext
from itertools import permutations
from random import Random

import pytest

from transactionshield.canonical import parse_canonical_row
from transactionshield.contracts import evaluation_partition, is_primary_model_eligible
from transactionshield.features import (
    CORE_FEATURE_NAMES, BehaviouralEvent, CoreFeatures, HistoryEngine,
    behavioural_event, exact_amount_sum, historical_amount_mean, iter_feature_examples,
)
from transactionshield.validation import APPROVED_ARTIFACT


def row(step=0, amount="1", initiator="A", recipient="B", kind="TRANSFER", number=2):
    return parse_canonical_row(
        [str(step), kind, amount, initiator, "-10.00", "-11.00", recipient, "2.00", "3.00", "0"],
        number, APPROVED_ARTIFACT.sha256,
    )


def keyed(rows, enhanced=True):
    return {example.lineage.transaction_id: example for example in iter_feature_examples(rows, enhanced=enhanced)}


def test_narrow_frozen_boundary_and_exact_predictor_schema():
    event = behavioural_event(row())
    assert {field.name for field in fields(event)} == {
        "step", "transaction_type", "amount", "initiator_id", "recipient_id",
    }
    assert not hasattr(event, "__dict__")
    for forbidden in ("is_fraud", "initiator_balance_after", "recipient_balance_after",
                      "transaction_id", "source_row_number", "initiator_balance_before"):
        assert not hasattr(event, forbidden)
    with pytest.raises(FrozenInstanceError):
        event.amount = Decimal("99")
    with pytest.raises(TypeError, match="narrow BehaviouralEvent"):
        HistoryEngine().process(row())
    assert CORE_FEATURE_NAMES == (
        "amount", "initiator_prior_outgoing_count", "initiator_prior_outgoing_transfer_count",
        "initiator_prior_outgoing_amount_total", "initiator_prior_outgoing_amount_mean",
        "initiator_prior_outgoing_amount_max", "recipient_prior_incoming_count",
        "initiator_prior_distinct_recipient_count", "recipient_prior_distinct_initiator_count",
    )


def test_richer_subclass_is_not_accepted_by_history():
    class RichEvent(BehaviouralEvent):
        is_fraud = 1
    with pytest.raises(TypeError):
        HistoryEngine().process(RichEvent(0, "TRANSFER", Decimal(1), "A", "B"))


def test_every_core_aggregate_and_all_type_history():
    rows = [
        row(0, "10", "A", "B", "TRANSFER", 2),
        row(0, "20", "A", "C", "PAYMENT", 3),
        row(0, "7", "D", "B", "DEPOSIT", 4),
        row(1, "5", "A", "B", "WITHDRAWAL", 5),
        row(1, "9", "A", "B", "DEBIT", 6),
        row(2, "100", "A", "B", "TRANSFER", 7),
    ]
    examples = list(iter_feature_examples(rows))
    assert len(examples) == 2
    assert examples[-1].core == CoreFeatures(
        Decimal(100), 4, 1, Decimal(44), Decimal(11), Decimal(20), 4, 2, 2,
    )
    assert examples[-1].enhanced is None


def test_cold_start_and_independent_entity_roles():
    rows = [row(0, "10", "A", "B"), row(1, "1", "B", "A", number=3)]
    for example in iter_feature_examples(rows):
        core = example.core
        assert core.initiator_prior_outgoing_count == 0
        assert core.initiator_prior_outgoing_transfer_count == 0
        assert core.recipient_prior_incoming_count == 0
        assert core.initiator_prior_outgoing_amount_total == Decimal(0)
        assert isinstance(core.initiator_prior_outgoing_amount_total, Decimal)
        assert core.initiator_prior_outgoing_amount_mean is None
        assert core.initiator_prior_outgoing_amount_max is None
        assert core.initiator_prior_distinct_recipient_count == 0
        assert core.recipient_prior_distinct_initiator_count == 0


def test_unseen_sender_and_recipient_are_independent():
    examples = list(iter_feature_examples([
        row(0, "4", "A", "B"), row(1, "1", "A", "new", number=3),
        row(1, "1", "new", "B", number=4),
    ]))
    assert examples[1].core.initiator_prior_outgoing_count == 1
    assert examples[1].core.recipient_prior_incoming_count == 0
    assert examples[2].core.initiator_prior_outgoing_count == 0
    assert examples[2].core.recipient_prior_incoming_count == 1


def test_same_step_permutations_pairs_new_counterparties_and_self_transfers():
    earlier = row(0, "2", "A", "B", number=2)
    same_step = [row(1, "3", "A", "C", number=3), row(1, "4", "D", "B", number=4),
                 row(1, "5", "A", "C", number=5), row(1, "6", "A", "A", number=6)]
    later = row(2, "1", "A", "B", number=7)
    expected = keyed([earlier, *same_step, later])
    for permutation in permutations(same_step):
        actual = keyed([earlier, *permutation, later])
        assert actual == expected
    for current in same_step:
        core = expected[current.transaction_id].core
        assert core.initiator_prior_outgoing_count == (1 if current.initiator_id == "A" else 0)
        assert core.recipient_prior_incoming_count == (1 if current.recipient_id == "B" else 0)
        assert core.initiator_prior_distinct_recipient_count == (1 if current.initiator_id == "A" else 0)
    assert expected[later.transaction_id].core.initiator_prior_outgoing_count == 4
    assert expected[later.transaction_id].core.initiator_prior_distinct_recipient_count == 3
    assert expected[later.transaction_id].core.recipient_prior_distinct_initiator_count == 2


def test_repeated_pair_is_counted_once_across_many_steps():
    examples = list(iter_feature_examples(row(t, number=t + 2) for t in range(20)))
    assert examples[-1].core.initiator_prior_outgoing_count == 19
    assert examples[-1].core.initiator_prior_distinct_recipient_count == 1
    assert examples[-1].core.recipient_prior_distinct_initiator_count == 1


def test_future_append_or_change_leaves_prefix_identical():
    prefix = [row(0), row(2, "3", number=3), row(2, "9", number=4)]
    expected = keyed(prefix)
    for future in (row(3, "10000", number=5), row(143, "0.001", "X", "A", number=5)):
        actual = keyed([*prefix, future])
        assert {key: actual[key] for key in expected} == expected


@pytest.mark.parametrize("change", [
    {"is_fraud": 1},
    {"initiator_balance_after": Decimal("999999"), "recipient_balance_after": Decimal("-444")},
])
def test_all_labels_and_post_balances_are_invisible(change):
    rows = [row(0), row(0, number=3), row(1, number=4), row(120, number=5)]
    assert keyed(rows) == keyed([replace(current, **change) for current in rows])


def test_enhanced_pre_balances_do_not_enter_core_history():
    rows = [row(0), row(1, number=3), row(120, number=4)]
    baseline = list(iter_feature_examples(rows, enhanced=True))
    changed = list(iter_feature_examples([
        replace(current, initiator_balance_before=Decimal("-123"),
                recipient_balance_before=Decimal("1234567890.001")) for current in rows
    ], enhanced=True))
    assert [example.core for example in changed] == [example.core for example in baseline]
    for before, after in zip(baseline, changed, strict=True):
        assert after.enhanced.core == before.core
        assert after.enhanced.initiator_balance_before == Decimal("-123")
        assert after.enhanced.recipient_balance_before == Decimal("1234567890.001")
        assert after.enhanced != before.enhanced


def test_non_transfer_rows_update_state_without_emitting_examples():
    for kind in ("DEBIT", "DEPOSIT", "PAYMENT", "WITHDRAWAL"):
        engine = HistoryEngine()
        assert engine.process(behavioural_event(row(kind=kind))) is None
        core = engine.process(behavioural_event(row(1)))
        assert core.initiator_prior_outgoing_count == core.recipient_prior_incoming_count == 1
        assert core.initiator_prior_outgoing_transfer_count == 0
    assert is_primary_model_eligible("TRANSFER")
    assert not is_primary_model_eligible("transfer")
    with pytest.raises(ValueError, match="transaction type"):
        BehaviouralEvent(0, "transfer", Decimal(1), "A", "B")


def test_partition_boundaries_never_reset_history():
    rows = [row(95, "1", number=2), row(96, "2", number=3), row(97, "3", number=4),
            row(119, "4", kind="PAYMENT", number=5), row(120, "5", number=6),
            row(121, "6", number=7)]
    examples = list(iter_feature_examples(rows))
    assert [evaluation_partition(example.lineage.step) for example in examples] == [
        "train", "validation", "validation", "test", "test",
    ]
    assert [example.core.initiator_prior_outgoing_count for example in examples] == [0, 1, 2, 4, 5]
    assert examples[3].core.initiator_prior_outgoing_amount_total == Decimal(10)
    assert examples[4].core.initiator_prior_outgoing_amount_total == Decimal(15)


@pytest.mark.parametrize(("step", "partition"), [(0, "train"), (95, "train"), (96, "validation"),
                                                    (119, "validation"), (120, "test"), (143, "test")])
def test_frozen_partition_assignment(step, partition):
    assert evaluation_partition(step) == partition


@pytest.mark.parametrize("step", [-1, 144, True, 1.0])
def test_evaluation_horizon_does_not_silently_expand(step):
    with pytest.raises(ValueError):
        evaluation_partition(step)


def test_missing_steps_and_arbitrary_lineage_do_not_define_chronology():
    rows = [row(0, "2", number=100), row(100, "3", number=2), row(100, "4", number=50)]
    examples = list(iter_feature_examples(rows))
    assert [example.core.initiator_prior_outgoing_count for example in examples] == [0, 1, 1]
    changed = [replace(current, source_row_number=999, transaction_id=rows[0].artifact_id) for current in rows]
    assert [example.core for example in iter_feature_examples(changed)] == [example.core for example in examples]


def test_regression_fails_and_never_commits_incomplete_step():
    engine = HistoryEngine()
    engine.process(behavioural_event(row(1)))
    assert engine.state_statistics()["committed_rows"] == 0
    with pytest.raises(ValueError, match="chronological regression"):
        engine.process(behavioural_event(row(0)))
    assert engine.state_statistics()["committed_rows"] == 0
    assert engine.state_statistics()["pending_rows"] == 0
    with pytest.raises(ValueError, match="failed"):
        engine.finish()


def test_pending_commits_only_at_step_boundary_and_successful_eof():
    engine = HistoryEngine()
    engine.process(behavioural_event(row(0)))
    engine.process(behavioural_event(row(0)))
    assert engine.state_statistics()["committed_rows"] == 0
    assert engine.state_statistics()["pending_rows"] == 2
    engine.process(behavioural_event(row(1)))
    assert engine.state_statistics()["committed_rows"] == 2
    assert engine.state_statistics()["pending_rows"] == 1
    engine.finish()
    assert engine.state_statistics()["committed_rows"] == 3
    assert engine.state_statistics()["pending_rows"] == 0
    with pytest.raises(ValueError, match="finished"):
        engine.process(behavioural_event(row(2)))


def test_malformed_upstream_or_early_close_aborts_pending():
    def broken():
        yield row(0)
        raise ValueError("upstream malformed row")
    engine = HistoryEngine()
    iterator = iter_feature_examples(broken(), engine=engine)
    next(iterator)
    with pytest.raises(ValueError, match="upstream malformed"):
        next(iterator)
    assert engine.state_statistics()["committed_rows"] == engine.state_statistics()["pending_rows"] == 0
    engine = HistoryEngine()
    iterator = iter_feature_examples([row(0), row(1)], engine=engine)
    next(iterator)
    iterator.close()
    with pytest.raises(ValueError, match="failed"):
        engine.finish()


def test_exact_sums_and_mean_independent_of_ambient_context():
    large = "123456789012345678901234567890.123456789"
    rows = [row(0, large), row(0, "0.000000001", number=3), row(0, "0.01", number=4),
            row(1, "1", number=5)]
    baseline = list(iter_feature_examples(rows))
    with localcontext() as ambient:
        ambient.prec = 2
        ambient.rounding = ROUND_DOWN
        ambient.Emax = 2
        ambient.Emin = -2
        ambient.traps[Inexact] = True
        actual = list(iter_feature_examples(rows))
    assert actual == baseline
    assert actual[-1].core.initiator_prior_outgoing_amount_total == Decimal(
        "123456789012345678901234567890.133456790")
    assert actual[-1].core.initiator_prior_outgoing_amount_max == Decimal(large)
    assert all(not isinstance(getattr(actual[-1].core, name), float) for name in CORE_FEATURE_NAMES)


def test_exact_sum_carry_and_scale_do_not_use_28_digit_rounding():
    with localcontext() as ambient:
        ambient.prec = 1
        assert exact_amount_sum(Decimal("999999999999999999999999999999.99"), Decimal("0.01")) == Decimal("1000000000000000000000000000000.00")


@pytest.mark.parametrize(("total", "count", "expected"), [
    ("1", 3, "0.3333333333333333333333333333"),
    ("2", 3, "0.6666666666666666666666666667"),
    ("1.2345678901234567890123456785", 1, "1.234567890123456789012345678"),
    ("1.2345678901234567890123456795", 1, "1.234567890123456789012345680"),
])
def test_explicit_mean_precision_and_half_even_ties(total, count, expected):
    with localcontext() as ambient:
        ambient.prec = 1
        ambient.rounding = ROUND_DOWN
        ambient.traps[Inexact] = True
        assert historical_amount_mean(Decimal(total), count) == Decimal(expected)
    assert historical_amount_mean(Decimal(0), 0) is None


@pytest.mark.parametrize("amount", [1.2, 1, Decimal("NaN"), Decimal("Infinity"), Decimal(0), Decimal(-1)])
def test_event_rejects_non_decimal_nonfinite_or_nonpositive_amount(amount):
    with pytest.raises(ValueError):
        BehaviouralEvent(0, "TRANSFER", amount, "A", "B")


def test_repeated_transactions_do_not_accumulate_event_objects():
    engine = HistoryEngine()
    for index in range(5000):
        engine.process(behavioural_event(row(index // 50)))
    engine.finish()
    stats = engine.state_statistics()
    assert stats["committed_rows"] == 5000
    assert stats["initiator_entities"] == stats["recipient_entities"] == stats["distinct_pairs"] == 1
    assert stats["interned_entity_strings"] == 2
    assert stats["pending_rows"] == stats["pending_new_pairs"] == 0


def test_small_randomised_replay_matches_independent_strict_prior_oracle():
    random = Random(904)
    rows = [row(step, str(random.randint(1, 100)), random.choice("ABC"), random.choice("ABC"),
                random.choice(("TRANSFER", "PAYMENT", "DEPOSIT")), step * 20 + index + 2)
            for step in range(5) for index in range(20)]
    examples = keyed(rows)
    for current in rows:
        if current.transaction_type != "TRANSFER":
            assert current.transaction_id not in examples
            continue
        outgoing = [prior for prior in rows if prior.step < current.step and prior.initiator_id == current.initiator_id]
        incoming = [prior for prior in rows if prior.step < current.step and prior.recipient_id == current.recipient_id]
        total = sum((prior.amount for prior in outgoing), Decimal(0))
        mean = Context(prec=28, rounding=ROUND_HALF_EVEN).divide(total, Decimal(len(outgoing))) if outgoing else None
        assert examples[current.transaction_id].core == CoreFeatures(
            current.amount, len(outgoing), sum(prior.transaction_type == "TRANSFER" for prior in outgoing),
            total, mean, max((prior.amount for prior in outgoing), default=None), len(incoming),
            len({prior.recipient_id for prior in outgoing}), len({prior.initiator_id for prior in incoming}),
        )
    assert keyed(rows) == examples
