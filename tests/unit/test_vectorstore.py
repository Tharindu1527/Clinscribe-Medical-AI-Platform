"""Vector-store comparison helpers (Phase 2 task 11): pgvector literal, exact top-k, overlap."""

import numpy as np

from evals.rag.vectorstore_eval import exact_top_k, overlap
from retrieval.pgvector_store import literal


def test_literal_is_pgvector_text_form() -> None:
    assert literal(np.array([0.5, -1.0, 1e-8], dtype=np.float32)) == "[0.5,-1,1e-08]"


def test_exact_top_k_ranks_by_cosine_on_normalised_rows() -> None:
    vectors = np.array([[1, 0], [0.6, 0.8], [0, 1], [-1, 0]], dtype=np.float32)
    queries = np.array([[0.8, 0.6], [0, -1]], dtype=np.float32)
    # q0 · rows = 0.8, 0.96, 0.6, -0.8; q1 · rows = 0, -0.8, -1, 0 (tie keeps row order)
    assert exact_top_k(queries, vectors, 3) == [[1, 0, 2], [0, 3, 1]]


def test_overlap_counts_shared_ids_in_the_top_k() -> None:
    exact = [f"c{i}" for i in range(10)]
    assert overlap(exact[::-1], exact) == 1.0
    assert overlap(["x", *exact[:9]], exact) == 0.9
