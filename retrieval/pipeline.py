"""The chosen retrieval pipeline (Phase 2, `evals/reports/rag/ablation.md`): dense + BM25 fused
with RRF over the contextual corpus, reranked by ColBERT. Built once per process; loading the
encoders and the BM25 index takes tens of seconds and ~1.5 GB of memory."""

from typing import Any

import yaml

from retrieval.dense import ROOT
from retrieval.rerank import RerankedRetriever

VARIANT = "contextual"


def build_chosen() -> RerankedRetriever:
    from retrieval.bm25 import BM25Retriever, load_index
    from retrieval.colbert import ColBERTConfig, ColBERTEncoder, build_store
    from retrieval.contextual import variant
    from retrieval.dense import (
        DenseRetriever,
        SentenceTransformerEncoder,
        connect,
        load_chunks,
        load_config,
    )
    from retrieval.hybrid import HybridRetriever
    from retrieval.rerank import ColBERTReranker, rerank_config

    corpus, suffix = variant(VARIANT)
    dense_cfg = load_config()
    dense_cfg = dense_cfg.model_copy(update={"collection": dense_cfg.collection + suffix})
    dense = DenseRetriever(
        dense_cfg, connect(), SentenceTransformerEncoder(dense_cfg, dense_cfg.query_prefix)
    )
    settings: dict[str, Any] = yaml.safe_load(
        (ROOT / "config" / "retrieval.yaml").read_text(encoding="utf-8")
    )
    hybrid = HybridRetriever(dense, BM25Retriever(load_index(corpus)), **settings["hybrid"])
    rerank = rerank_config()
    colbert = ColBERTConfig.model_validate(rerank["colbert"])
    chunks, sha = load_chunks(corpus)

    def must_be_built(*_: Any) -> Any:
        raise RuntimeError("ColBERT store missing; run `just index-colbert --variant contextual`")

    store, _ = build_store(colbert, chunks, sha, must_be_built)
    reranker = ColBERTReranker(ColBERTEncoder(colbert), store)
    return RerankedRetriever(hybrid, reranker, depth=rerank["depth"])
