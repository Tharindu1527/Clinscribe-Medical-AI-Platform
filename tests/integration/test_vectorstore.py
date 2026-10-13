"""PROGRESS Phase 2 task 11: pgvector holds the contextual vectors and exact search matches numpy.

Needs `just up vectorstore` and one `just vectorstore` run (loads the table); skipped otherwise
unless CLINSCRIBE_REQUIRE_RAG=1.
"""

import os
from typing import Any

import numpy as np
import psycopg
import pytest
from psycopg import sql

from evals.rag.vectorstore_eval import exact_top_k
from retrieval.pgvector_store import TABLE, PgVectorRetriever, connect


@pytest.fixture(scope="module")
def conn() -> psycopg.Connection[Any]:
    try:
        conn = connect()
        loaded = conn.execute("SELECT to_regclass(%s) IS NOT NULL", (TABLE,)).fetchone()
    except psycopg.Error:
        loaded = None
    if not loaded or not loaded[0]:
        if os.environ.get("CLINSCRIBE_REQUIRE_RAG") == "1":
            pytest.fail("pgvector table not loaded (just up vectorstore; just vectorstore)")
        pytest.skip("pgvector table not loaded (just up vectorstore; just vectorstore)")
    return conn


def test_table_and_hnsw_index_exist(conn: psycopg.Connection[Any]) -> None:
    count = conn.execute(
        sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(TABLE))
    ).fetchone()
    assert count is not None
    assert count[0] >= 8000
    index = conn.execute(
        "SELECT indexdef FROM pg_indexes WHERE tablename = %s AND indexname = %s",
        (TABLE, f"{TABLE}_hnsw"),
    ).fetchone()
    assert index is not None
    assert "hnsw" in index[0]
    assert "vector_cosine_ops" in index[0]


def test_exact_search_matches_numpy_and_hnsw_finds_the_same(
    conn: psycopg.Connection[Any],
) -> None:
    rows = conn.execute(
        sql.SQL("SELECT chunk_id, embedding::text FROM {} ORDER BY chunk_id").format(
            sql.Identifier(TABLE)
        )
    )
    ids, vectors = [], []
    for chunk_id, text in rows.fetchall():
        ids.append(chunk_id)
        vectors.append(np.array(text.strip("[]").split(","), dtype=np.float32))
    matrix = np.stack(vectors)
    for row in (17, 4000):  # stored vectors: each one's own chunk must come first
        query = matrix[row]
        expected = [ids[j] for j in exact_top_k(query[None, :], matrix, 5)[0]]
        exact = PgVectorRetriever(conn, exact=True).search_vector(query, k=5)
        assert [h.chunk_id for h in exact] == expected
        assert exact[0].chunk_id == ids[row]
        assert exact[0].score > 0.999
        approximate = PgVectorRetriever(conn, ef_search=100).search_vector(query, k=5)
        assert approximate[0].chunk_id == ids[row]
