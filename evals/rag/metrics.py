"""Retrieval metrics and a paired bootstrap for comparing two systems on the same questions.

Relevance is binary: a retrieved chunk is relevant if it is one of the question's gold chunks
(every chunk that contains the quoted answer, see evals/golden). Gold chunks are usually the same
passage twice (overlapping neighbours), so recall is answer-level: a question is found when ANY
gold chunk is in the top k.
"""

import math
import random
from collections.abc import Sequence


def recall_at_k(ranked: Sequence[str], gold: set[str], k: int = 10) -> float:
    """1.0 if any gold chunk is in the top k, else 0.0 (answer-level recall / hit rate)."""
    return 1.0 if gold.intersection(ranked[:k]) else 0.0


def reciprocal_rank(ranked: Sequence[str], gold: set[str], k: int = 10) -> float:
    """1 / rank of the first gold chunk within the top k; 0.0 if none (MRR@k per question)."""
    for rank, chunk_id in enumerate(ranked[:k], start=1):
        if chunk_id in gold:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(ranked: Sequence[str], gold: set[str], k: int = 10) -> float:
    """Binary-relevance nDCG@k; the ideal ranking puts min(|gold|, k) gold chunks first."""
    dcg = sum(1.0 / math.log2(rank + 1) for rank, c in enumerate(ranked[:k], 1) if c in gold)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(len(gold), k) + 1))
    return dcg / ideal if ideal else 0.0


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile (q in 0..1), as used by the other latency reports."""
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(q * (len(ordered) - 1))))
    return ordered[index]


def paired_bootstrap(
    baseline: Sequence[float], candidate: Sequence[float], n: int = 10_000, seed: int = 42
) -> tuple[float, float, float]:
    """Mean of (candidate - baseline) per question and its 95% percentile bootstrap interval.

    Questions are resampled with replacement, keeping each question's pair together, so the
    interval reflects how much the difference depends on which questions happen to be in the set.
    """
    if len(baseline) != len(candidate) or not baseline:
        raise ValueError("need two equal-length, non-empty score lists")
    diffs = [c - b for b, c in zip(baseline, candidate, strict=True)]
    rng = random.Random(seed)
    size = len(diffs)
    means = sorted(sum(rng.choices(diffs, k=size)) / size for _ in range(n))
    return sum(diffs) / size, means[int(0.025 * n)], means[int(0.975 * n) - 1]
