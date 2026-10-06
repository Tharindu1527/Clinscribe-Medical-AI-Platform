"""Hybrid search: dense and BM25 run in parallel and their rankings merge with reciprocal rank
fusion (RRF, Cormack et al. 2009): fused(d) = sum over lists of 1 / (k + rank(d)).

RRF uses ranks only, so the two score scales (cosine vs BM25) never need calibrating. k = 60 is
the published default and is not tuned on the golden set.
"""

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

from privacy.deid.types import DeidentifiedText
from retrieval.dense import Hit


class Retriever(Protocol):
    def search(self, query: DeidentifiedText, k: int = 10) -> list[Hit]: ...


def rrf(rankings: Sequence[Sequence[str]], k: int = 60) -> list[Hit]:
    """Fuse ranked id lists. Ties go to the id with the better best rank, then to id order."""
    fused: dict[str, float] = {}
    best: dict[str, int] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (k + rank)
            best[chunk_id] = min(best.get(chunk_id, rank), rank)
    order = sorted(fused, key=lambda c: (-fused[c], best[c], c))
    return [Hit(chunk_id=c, score=fused[c]) for c in order]


class HybridRetriever:
    def __init__(self, dense: Retriever, bm25: Retriever, rrf_k: int = 60, depth: int = 50) -> None:
        self._retrievers = (dense, bm25)
        self._rrf_k = rrf_k
        self._depth = depth
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="hybrid")

    def search(self, query: DeidentifiedText, k: int = 10) -> list[Hit]:
        if not isinstance(query, DeidentifiedText):
            raise TypeError("HybridRetriever.search accepts only DeidentifiedText")
        futures = [self._pool.submit(r.search, query, self._depth) for r in self._retrievers]
        rankings = [[hit.chunk_id for hit in f.result()] for f in futures]
        return rrf(rankings, self._rrf_k)[:k]
