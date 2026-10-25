"""Metric code of the offline citation-support evaluation (ADR-0017), on hand-worked cases."""

import pytest

from evals.rag.citation_support import (
    Link,
    auc,
    best_in_sentence,
    keep,
    pick_threshold,
    precision,
    softmax_entailment,
    windows,
)

pytestmark = pytest.mark.unit


def _link(question: str, sentence: int, text: str = "", rating: str = "supports") -> Link:
    return Link("p", question, sentence, "c", rating, "h", "premise", "T — S. ", text)


def test_auc_counts_pairs_and_ties_count_half() -> None:
    assert auc([0.9, 0.8, 0.1], [True, True, False]) == 1.0
    assert auc([0.1, 0.9], [True, False]) == 0.0
    assert auc([0.5, 0.5], [True, False]) == 0.5


def test_precision_of_kept_links_and_nothing_kept_counts_as_precise() -> None:
    assert precision([True, True, False], [True, False, False]) == 0.5
    assert precision([False, False], [True, False]) == 1.0


def test_the_lowest_threshold_reaching_the_target_is_picked() -> None:
    scores = [0.9, 0.8, 0.3, 0.2]
    positive = [True, True, False, True]
    best = [False] * 4
    # t 0.2 keeps all (0.75), t 0.3 keeps three (0.67), t 0.8 keeps two (1.0) -> 0.8
    assert pick_threshold(scores, best, positive, "threshold") == 0.8


def test_best_kept_never_leaves_a_sentence_without_its_top_citation() -> None:
    links = [_link("q1", 1), _link("q1", 1), _link("q1", 2)]
    best = best_in_sentence(links, [0.2, 0.6, 0.1])
    assert best == [False, True, True]
    assert keep([0.2, 0.6, 0.1], best, 0.5, "best kept") == [False, True, True]
    assert keep([0.2, 0.6, 0.1], best, 0.5, "threshold") == [False, True, False]


def test_windows_are_two_sentences_with_the_heading_and_entailment_is_the_middle_label() -> None:
    link = _link("q", 1, "First one. Second one; Third one. Fourth; and a clause.")
    assert windows(link) == [  # a new sentence starts only before a capital or digit
        "T — S. First one. Second one;",
        "T — S. Second one; Third one.",
        "T — S. Third one. Fourth; and a clause.",
    ]
    assert windows(_link("q", 1, "Only one sentence")) == ["T — S. Only one sentence"]
    assert softmax_entailment([0.0, 0.0, 0.0]) == pytest.approx(1 / 3)
    assert softmax_entailment([0.0, 10.0, 0.0]) > 0.99
