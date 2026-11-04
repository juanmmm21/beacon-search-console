"""Métricas de evaluación contra valores calculados a mano."""

from __future__ import annotations

import math

import pytest

from beacon_search_console.evaluation.metrics import (
    evaluate_run,
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
)


def test_ndcg_perfect_ranking_is_one() -> None:
    judgments = {"a": 2, "b": 1}
    assert math.isclose(ndcg_at_k(["a", "b", "c"], judgments, 10), 1.0)


def test_ndcg_hand_computed_with_linear_gain() -> None:
    # dcg = 1/log2(2) + 2/log2(4) = 1 + 1 = 2 ; idcg = 2/1 + 1/log2(3)
    judgments = {"a": 2, "b": 1}
    expected = 2.0 / (2.0 + 1.0 / math.log2(3))
    assert math.isclose(ndcg_at_k(["b", "x", "a"], judgments, 10), expected)


def test_ndcg_ideal_uses_all_judgments_not_only_retrieved() -> None:
    judgments = {"a": 1, "b": 1}
    expected = 1.0 / (1.0 + 1.0 / math.log2(3))
    assert math.isclose(ndcg_at_k(["a"], judgments, 10), expected)


def test_ndcg_respects_cutoff() -> None:
    assert ndcg_at_k(["x", "a"], {"a": 1}, 1) == 0.0


def test_mrr_first_relevant_rank() -> None:
    assert math.isclose(mrr_at_k(["x", "y", "a"], {"a": 1}, 10), 1 / 3)
    assert mrr_at_k(["x", "y", "a"], {"a": 1}, 2) == 0.0
    assert mrr_at_k(["x"], {"x": 0}, 10) == 0.0


def test_recall_fraction_of_relevant() -> None:
    assert math.isclose(recall_at_k(["a", "x"], {"a": 1, "b": 2, "c": 0}, 100), 0.5)


@pytest.mark.parametrize("function", [ndcg_at_k, mrr_at_k, recall_at_k])
def test_invalid_k_rejected(function: object) -> None:
    with pytest.raises(ValueError):
        function(["a"], {"a": 1}, 0)  # type: ignore[operator]


def test_evaluate_run_skips_queries_without_positive_judgment() -> None:
    qrels = {"q1": {"a": 1}, "q2": {"b": 0}, "q3": {"c": 1}}
    run = {"q1": ["a"], "q2": ["b"]}
    metrics = evaluate_run(run, qrels)
    assert metrics.evaluated_queries == 2
    assert metrics.skipped_queries == 1
    # q3 no está en el run: cuenta como ranking vacío, no se ignora.
    assert math.isclose(metrics.ndcg_at_10, 0.5)
    assert math.isclose(metrics.recall_at_100, 0.5)
