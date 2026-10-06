"""Retrieval metrics on hand-worked cases, and the report pipeline on a fake run (no model)."""

import math

import pytest

from evals.golden.golden import GoldenItem
from evals.rag.metrics import (
    ndcg_at_k,
    paired_bootstrap,
    percentile,
    recall_at_k,
    reciprocal_rank,
)
from evals.rag.retrieval_eval import summarise

RANKED = ["a", "b", "c", "d", "e"]


def test_recall_is_answer_level_hit_within_k() -> None:
    gold = {"c", "x"}  # x is never retrieved; one gold chunk is enough
    assert recall_at_k(RANKED, gold, 1) == 0.0
    assert recall_at_k(RANKED, gold, 2) == 0.0
    assert recall_at_k(RANKED, gold, 3) == 1.0
    assert recall_at_k(RANKED, set(), 5) == 0.0


def test_reciprocal_rank_uses_the_first_gold_chunk_and_the_cutoff() -> None:
    assert reciprocal_rank(RANKED, {"c", "e"}) == pytest.approx(1 / 3)
    assert reciprocal_rank(RANKED, {"a"}) == 1.0
    assert reciprocal_rank(RANKED, {"e"}, k=4) == 0.0


def test_ndcg_hand_worked() -> None:
    # gold {c, x}: DCG = 1/log2(4) = 0.5; ideal = 1/log2(2) + 1/log2(3) = 1.6309
    expected = 0.5 / (1 + 1 / math.log2(3))
    assert ndcg_at_k(RANKED, {"c", "x"}, k=5) == pytest.approx(expected)
    assert expected == pytest.approx(0.3066, abs=1e-4)
    assert ndcg_at_k(RANKED, {"a", "b"}, k=5) == pytest.approx(1.0)  # perfect order
    assert ndcg_at_k(RANKED, {"z"}, k=5) == 0.0


def test_percentile_is_nearest_rank() -> None:
    values = [float(v) for v in range(1, 101)]
    assert percentile(values, 0.5) == 51.0  # round(0.5 * 99) = 50 -> 51st value
    assert percentile(values, 0.95) == 95.0


def test_paired_bootstrap_detects_a_consistent_gain_and_not_noise() -> None:
    same = [0.0, 1.0, 1.0, 0.0] * 25
    assert paired_bootstrap(same, same) == (0.0, 0.0, 0.0)
    diff, low, high = paired_bootstrap([0.0] * 100, [1.0] * 100)
    assert (diff, low, high) == (1.0, 1.0, 1.0)
    noisy_base = [0.0, 1.0] * 50
    noisy_cand = [1.0, 0.0] * 50  # same mean, opposite per question
    diff, low, high = paired_bootstrap(noisy_base, noisy_cand)
    assert diff == 0.0
    assert low < 0 < high
    with pytest.raises(ValueError, match="equal-length"):
        paired_bootstrap([1.0], [1.0, 0.0])


def _item(item_id: str, gold: list[str], area: str = "diabetes") -> GoldenItem:
    answerable = bool(gold)
    return GoldenItem(
        id=item_id,
        question=f"Synthetic question number {item_id}?",
        answerable=answerable,
        answer="a quoted answer" if answerable else None,
        gold_chunk_ids=gold,
        absent_terms=[] if answerable else ["zzz"],
        area=area,
        qtype="fact",
        source="pmc" if answerable else None,
        drafted_by="test",
    )


def test_summary_breaks_down_by_area_and_lists_misses() -> None:
    items = [_item("g0001", ["c"]), _item("g0002", ["z"], "infections"), _item("g0003", [])]
    run = {
        "system": "fake",
        "results": {
            "g0001": {"ms": 10.0, "ranked": RANKED, "scores": [0.9, 0.8]},
            "g0002": {"ms": 30.0, "ranked": RANKED, "scores": [0.7]},
            "g0003": {"ms": 20.0, "ranked": RANKED, "scores": [0.4]},
        },
    }
    summary = summarise(run, items)
    assert summary["n_answerable"] == 2  # the unanswerable item is not scored
    assert summary["overall"]["recall@10"] == 0.5
    assert summary["overall"]["mrr@10"] == pytest.approx((1 / 3 + 0) / 2)
    assert summary["breakdown"]["area"]["diabetes"]["recall@10"] == 1.0
    assert summary["breakdown"]["area"]["infections"]["recall@10"] == 0.0
    assert summary["misses_at_10"] == ["g0002"]
    # nearest-rank median of [0.7, 0.9]: round(0.5 * 1) = 0 -> 0.7
    assert summary["top1_score_median"] == {"answerable": 0.7, "unanswerable": 0.4}
    assert summary["latency_ms"]["p50"] == 20.0
