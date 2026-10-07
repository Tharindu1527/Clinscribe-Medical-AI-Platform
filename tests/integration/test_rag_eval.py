"""PROGRESS Phase 2 task 4: the retrieval harness runs end to end against the dense index.

Uses five golden questions only (the full run is `just eval rag`). Needs `just up rag` and
`just index`; skipped otherwise unless CLINSCRIBE_REQUIRE_RAG=1.
"""

import os

import pytest

from evals.golden.golden import load_items
from evals.rag.retrieval_eval import METRICS, STORED_K, run_system, summarise
from retrieval.dense import connect, load_config


def test_dense_run_ranks_chunks_for_every_question_and_scores_them() -> None:
    try:
        ready = connect().collection_exists(load_config().collection)
    except Exception:  # noqa: BLE001 - Qdrant down or unreachable
        ready = False
    if not ready:
        if os.environ.get("CLINSCRIBE_REQUIRE_RAG") == "1":
            pytest.fail("dense index not available (just up rag; just index)")
        pytest.skip("dense index not available (just up rag; just index)")
    items = load_items()[:4] + [i for i in load_items() if not i.answerable][:1]
    run = run_system("dense", items)
    assert set(run["results"]) == {i.id for i in items}
    assert all(len(r["ranked"]) == STORED_K for r in run["results"].values())
    summary = summarise(run, items)
    assert summary["n_answerable"] == 4
    assert all(0.0 <= summary["overall"][m] <= 1.0 for m in METRICS)
    assert summary["latency_ms"]["p95"] >= summary["latency_ms"]["p50"] > 0


def test_colbert_store_matches_the_corpus_and_reranks_a_drug_question() -> None:
    from privacy.deid.types import issue
    from retrieval.colbert import ColBERTEncoder, build_store, store_dir
    from retrieval.colbert import load_config as colbert_config
    from retrieval.dense import DenseRetriever, SentenceTransformerEncoder, load_chunks
    from retrieval.rerank import ColBERTReranker, RerankedRetriever

    cfg = colbert_config()
    chunks, sha = load_chunks()
    if not (store_dir(cfg, sha) / "meta.json").exists():
        if os.environ.get("CLINSCRIBE_REQUIRE_RAG") == "1":
            pytest.fail("ColBERT store not built (just index-colbert)")
        pytest.skip("ColBERT store not built (just index-colbert)")
    store, meta = build_store(cfg, chunks, sha, ColBERTEncoder)  # loads; never re-encodes here
    assert meta["chunks"] == len(chunks)
    dense_cfg = load_config()
    dense = DenseRetriever(
        dense_cfg, connect(), SentenceTransformerEncoder(dense_cfg, dense_cfg.query_prefix)
    )
    retriever = RerankedRetriever(dense, ColBERTReranker(ColBERTEncoder(cfg), store), depth=30)
    hits = retriever.search(
        issue("Which drugs increase the bleeding risk of warfarin?", "synthetic-test-fixture"), k=5
    )
    texts = {c["id"]: c["text"].lower() for c in chunks}
    assert sum("warfarin" in texts[h.chunk_id] for h in hits) >= 3
