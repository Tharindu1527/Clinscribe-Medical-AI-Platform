"""BM25, reciprocal rank fusion and the hybrid retriever on hand-worked cases."""

import math

import pytest

from privacy.deid.types import DeidentifiedText, issue
from retrieval.bm25 import BM25Index, BM25Retriever, tokenize
from retrieval.dense import Hit
from retrieval.hybrid import HybridRetriever, rrf


def test_tokenize_lowercases_drops_stopwords_keeps_negation_and_folds_plurals() -> None:
    assert tokenize("ACE inhibitors are NOT first-line in pregnancy") == [
        "ace", "inhibitor", "not", "first", "line", "pregnancy"
    ]  # fmt: skip
    # "ss", "us" and "is" endings are not plurals; short words are left alone
    assert tokenize("class status analysis lungs dogs") == [
        "class",
        "status",
        "analysis",
        "lung",
        "dogs",
    ]
    assert tokenize("BP 140/90 mmHg") == ["bp", "140", "90", "mmhg"]


def _index() -> BM25Index:
    return BM25Index(
        ["d0", "d1", "d2"], ["warfarin bleeding risk", "warfarin dose", "metformin dose"]
    )


def test_bm25_scores_match_the_hand_worked_formula() -> None:
    # N = 3, avgdl = 7/3; "warfarin" occurs in 2 chunks: idf = ln(1 + 1.5 / 2.5) = ln 1.6
    idf = math.log(1.6)
    norm0 = 1.2 * (0.25 + 0.75 * 3 / (7 / 3))  # d0 has 3 tokens
    norm1 = 1.2 * (0.25 + 0.75 * 2 / (7 / 3))  # d1 has 2 tokens
    scores = _index().scores("warfarin")
    assert scores[0] == pytest.approx(idf * 2.2 / (1 + norm0))
    assert scores[1] == pytest.approx(idf * 2.2 / (1 + norm1))
    assert scores[0] == pytest.approx(0.4208, abs=1e-4)
    assert scores[1] == pytest.approx(0.4992, abs=1e-4)  # shorter chunk scores higher
    assert scores[2] == 0.0


def test_bm25_top_returns_only_matches_in_score_order() -> None:
    index = _index()
    # d1 matches both terms; "dose" and "warfarin" share an idf, so the shorter d2 (0.4992)
    # beats d0 (0.4208)
    assert [h.chunk_id for h in index.top("warfarin dose", 10)] == ["d1", "d2", "d0"]
    assert index.top("insulin", 10) == []  # unknown term: no results rather than random ones
    assert [h.chunk_id for h in index.top("dose", 10)] == ["d1", "d2"]  # tie: corpus order


def test_bm25_retriever_accepts_only_deidentified_text() -> None:
    retriever = BM25Retriever(_index())
    assert retriever.search(issue("warfarin", "synthetic-test-fixture"), k=1)[0].chunk_id == "d1"
    with pytest.raises(TypeError):
        retriever.search("warfarin", k=1)  # type: ignore[arg-type]


def test_rrf_hand_worked() -> None:
    # k = 60: c = 1/63 + 1/61, a = 1/61, b = d = 1/62 (tie: same best rank 2 -> id order)
    fused = rrf([["a", "b", "c"], ["c", "d"]], k=60)
    assert [h.chunk_id for h in fused] == ["c", "a", "b", "d"]
    assert fused[0].score == pytest.approx(1 / 63 + 1 / 61)
    assert fused[2].score == pytest.approx(1 / 62)
    assert rrf([], k=60) == []


def test_rrf_rewards_agreement_over_a_single_high_rank() -> None:
    # "x" is 3rd in both lists; "y" is 1st in one list only: 2/63 > 1/61
    fused = rrf([["y", "p", "x"], ["q", "r", "x"]], k=60)
    assert fused[0].chunk_id == "x"


class _Fixed:
    def __init__(self, ids: list[str]) -> None:
        self.ids = ids
        self.depths: list[int] = []

    def search(self, query: DeidentifiedText, k: int = 10) -> list[Hit]:
        self.depths.append(k)
        return [Hit(chunk_id=c, score=1.0) for c in self.ids[:k]]


def test_hybrid_fuses_both_lists_at_the_configured_depth() -> None:
    dense, bm25 = _Fixed(["a", "b", "c"]), _Fixed(["c", "d"])
    hybrid = HybridRetriever(dense, bm25, rrf_k=60, depth=50)
    hits = hybrid.search(issue("query", "synthetic-test-fixture"), k=2)
    assert [h.chunk_id for h in hits] == ["c", "a"]
    assert dense.depths == bm25.depths == [50]
    with pytest.raises(TypeError):
        hybrid.search("query", k=2)  # type: ignore[arg-type]
