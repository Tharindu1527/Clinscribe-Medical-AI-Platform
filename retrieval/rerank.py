"""Rerankers over a first-stage candidate pool (ablation step 3).

- Cross-encoder: reads (question, chunk) together and outputs one relevance score per pair; all
  candidates are scored at query time.
- ColBERT: scores late interaction (MaxSim) between the question's token vectors and each
  candidate's precomputed token vectors (retrieval/colbert.py); only the query is encoded at
  query time.

A RerankedRetriever takes the top `depth` candidates from a first-stage retriever (dense or
hybrid) and reorders them, so recall@depth of the first stage is the ceiling for the reranker.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

import yaml

from privacy.deid.types import DeidentifiedText
from retrieval.colbert import ROOT, ColBERTEncoder, DocStore, maxsim
from retrieval.dense import Hit


class Retriever(Protocol):
    def search(self, query: DeidentifiedText, k: int = 10) -> list[Hit]: ...


class Reranker(Protocol):
    def rerank(self, query: DeidentifiedText, candidates: Sequence[Hit]) -> list[Hit]: ...


def rerank_config() -> dict[str, Any]:
    cfg: dict[str, Any] = yaml.safe_load(
        (ROOT / "config" / "retrieval.yaml").read_text(encoding="utf-8")
    )["rerank"]
    return cfg


def _ordered(ids: Sequence[str], scores: Sequence[float]) -> list[Hit]:
    """Highest score first; ties keep the first-stage order (stable sort)."""
    order = sorted(range(len(ids)), key=lambda i: -scores[i])
    return [Hit(chunk_id=ids[i], score=float(scores[i])) for i in order]


class CrossEncoderReranker:
    def __init__(
        self,
        texts: Mapping[str, str],
        model: str,
        revision: str,
        max_length: int = 512,
        batch_size: int = 32,
        device: str = "cpu",
    ) -> None:
        from sentence_transformers import CrossEncoder  # heavy import (torch): lazy

        self._texts = texts
        self._batch_size = batch_size
        self._model = CrossEncoder(
            model, revision=revision, max_length=max_length, device=device, trust_remote_code=False
        )

    def rerank(self, query: DeidentifiedText, candidates: Sequence[Hit]) -> list[Hit]:
        if not isinstance(query, DeidentifiedText):
            raise TypeError("rerank accepts only DeidentifiedText")
        if not candidates:
            return []
        ids = [h.chunk_id for h in candidates]
        pairs = [(query.text, self._texts[c]) for c in ids]
        scores = self._model.predict(pairs, batch_size=self._batch_size, show_progress_bar=False)
        return _ordered(ids, [float(s) for s in scores])


class ColBERTReranker:
    def __init__(self, encoder: ColBERTEncoder, store: DocStore) -> None:
        self._encoder = encoder
        self._store = store

    def rerank(self, query: DeidentifiedText, candidates: Sequence[Hit]) -> list[Hit]:
        if not isinstance(query, DeidentifiedText):
            raise TypeError("rerank accepts only DeidentifiedText")
        if not candidates:
            return []
        q = self._encoder.encode_queries([query.text])[0]
        ids = [h.chunk_id for h in candidates]
        return _ordered(ids, [maxsim(q, self._store.get(c)) for c in ids])


class RerankedRetriever:
    def __init__(self, first_stage: Retriever, reranker: Reranker, depth: int = 30) -> None:
        self._first_stage = first_stage
        self._reranker = reranker
        self._depth = depth

    def search(self, query: DeidentifiedText, k: int = 10) -> list[Hit]:
        if not isinstance(query, DeidentifiedText):
            raise TypeError("RerankedRetriever.search accepts only DeidentifiedText")
        candidates = self._first_stage.search(query, k=self._depth)
        return self._reranker.rerank(query, candidates)[:k]
