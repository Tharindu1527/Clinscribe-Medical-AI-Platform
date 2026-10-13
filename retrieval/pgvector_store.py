"""pgvector store for the vector-store comparison (Phase 2 task 11, ADR-0007).

Holds the same cached chunk vectors as the Qdrant dense collection (no re-embedding) in a table
with an HNSW index (cosine). Exact search turns index scans off for one transaction, which gives
the ground truth that approximate search is measured against. Only the comparison uses it; the
retrieval pipeline stays on Qdrant unless ADR-0007 says otherwise.
"""

import time
from collections.abc import Sequence
from typing import Any

import numpy as np
import psycopg
from numpy.typing import NDArray
from psycopg import sql

from config.settings import Settings
from privacy.deid.types import DeidentifiedText
from retrieval.dense import Encoder, Hit

TABLE = "chunks_dense_ctx"


def connect(settings: Settings | None = None) -> psycopg.Connection[Any]:
    settings = settings or Settings()
    return psycopg.connect(
        settings.pgvector_url,
        password=settings.pgvector_password.get_secret_value(),
        connect_timeout=10,
        autocommit=True,
    )


def literal(vector: Sequence[float] | NDArray[np.float32]) -> str:
    """pgvector's text form, '[0.1,0.2,...]'."""
    return "[" + ",".join(f"{float(x):.7g}" for x in vector) + "]"


def load_table(
    conn: psycopg.Connection[Any],
    chunk_ids: Sequence[str],
    vectors: NDArray[np.float32],
    fingerprint: str,
    table: str = TABLE,
) -> dict[str, Any]:
    """One row per chunk; skipped when the table already holds these vectors."""
    name = sql.Identifier(table)
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    stored = conn.execute(
        "SELECT obj_description(to_regclass(%s), 'pg_class')", (table,)
    ).fetchone()
    if stored and stored[0] == fingerprint:
        count = conn.execute(sql.SQL("SELECT count(*) FROM {}").format(name)).fetchone()
        if count and count[0] == len(chunk_ids):
            return {"loaded": 0}
    dim = int(vectors.shape[1])
    conn.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(name))
    conn.execute(
        sql.SQL("CREATE TABLE {} (chunk_id text PRIMARY KEY, embedding vector({}))").format(
            name, sql.Literal(dim)
        )
    )
    started = time.perf_counter()
    with (
        conn.cursor() as cur,
        cur.copy(sql.SQL("COPY {} (chunk_id, embedding) FROM STDIN").format(name)) as copy,
    ):
        for chunk_id, vector in zip(chunk_ids, vectors, strict=True):
            copy.write_row((chunk_id, literal(vector)))
    loaded = time.perf_counter() - started
    conn.execute(sql.SQL("COMMENT ON TABLE {} IS {}").format(name, sql.Literal(fingerprint)))
    return {"loaded": len(chunk_ids), "load_seconds": round(loaded, 1)}


def build_hnsw(
    conn: psycopg.Connection[Any], m: int, ef_construction: int, table: str = TABLE
) -> float:
    """(Re)build the cosine HNSW index; returns build seconds."""
    index = sql.Identifier(f"{table}_hnsw")
    conn.execute(sql.SQL("DROP INDEX IF EXISTS {}").format(index))
    started = time.perf_counter()
    conn.execute(
        sql.SQL(
            "CREATE INDEX {} ON {} USING hnsw (embedding vector_cosine_ops) "
            "WITH (m = {}, ef_construction = {})"
        ).format(index, sql.Identifier(table), sql.Literal(m), sql.Literal(ef_construction))
    )
    conn.execute(sql.SQL("ANALYZE {}").format(sql.Identifier(table)))
    return time.perf_counter() - started


class PgVectorRetriever:
    """Top-k by cosine distance; exact=True scans every row instead of using the index."""

    def __init__(
        self,
        conn: psycopg.Connection[Any],
        encoder: Encoder | None = None,
        *,
        exact: bool = False,
        ef_search: int = 40,
        table: str = TABLE,
    ) -> None:
        self._conn = conn
        self._encoder = encoder
        self._exact = exact
        self._ef_search = ef_search
        self._query = sql.SQL(
            "SELECT chunk_id, 1 - (embedding <=> %s::vector) FROM {} "
            "ORDER BY embedding <=> %s::vector LIMIT %s"
        ).format(sql.Identifier(table))

    def search_vector(self, vector: NDArray[np.float32], k: int = 10) -> list[Hit]:
        text = literal(vector)
        with self._conn.transaction(), self._conn.cursor() as cur:
            if self._exact:
                cur.execute("SET LOCAL enable_indexscan = off")
            else:
                cur.execute(
                    sql.SQL("SET LOCAL hnsw.ef_search = {}").format(sql.Literal(self._ef_search))
                )
            rows = cur.execute(self._query, (text, text, k)).fetchall()
        return [Hit(chunk_id=str(chunk_id), score=float(score)) for chunk_id, score in rows]

    def search(self, query: DeidentifiedText, k: int = 10) -> list[Hit]:
        """Same contract as DenseRetriever: only de-identified text reaches the encoder."""
        if not isinstance(query, DeidentifiedText):
            raise TypeError("PgVectorRetriever.search accepts only DeidentifiedText")
        if self._encoder is None:
            raise ValueError("no encoder: use search_vector")
        return self.search_vector(self._encoder.encode([query.text])[0], k)
