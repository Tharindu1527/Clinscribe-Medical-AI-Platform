"""Vector-store comparison: Qdrant vs pgvector on recall and latency (Phase 2 task 11, ADR-0007).

Both stores hold the same cached contextual chunk vectors (ModernBERT Embed, 8,104 x 768, no
re-embedding), and every system answers the same 209 answerable golden questions from the same
query vectors, so the stores are compared and not the encoder. Systems:
- qdrant: the deployed collection. Its segments are below Qdrant's indexing threshold, so it is
  not HNSW-indexed and searches exactly.
- qdrant_hnsw_ef*: a copy with HNSW forced (m 16, ef_construct 100), searched with hnsw_ef 40/100.
- pgvector_exact: sequential scan (index scans off), exact like the deployed Qdrant.
- pgvector_hnsw_ef*: HNSW with the same m and ef_construction, ef_search 40 (pgvector default)/100.
Measured per system: golden recall@10 and nDCG@10, overlap@10 with exact nearest neighbours
(numpy), query latency p50/p95 over ROUNDS warm passes (store only: query vectors precomputed),
plus build time, memory and disk.

  just up rag; just up vectorstore; uv run python -m evals.rag.vectorstore_eval
  (report in evals/reports/rag/vectorstore.md; the Qdrant HNSW copy is deleted afterwards)
"""

import json
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from evals.golden.golden import load_items
from evals.rag.metrics import ndcg_at_k, paired_bootstrap, percentile, recall_at_k

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "evals" / "reports" / "rag"
K = 10
ROUNDS = 3
HNSW_M = 16
HNSW_EF_CONSTRUCT = 100  # Qdrant's default; pgvector's default is 64
EF_SEARCH = (40, 100)

Search = Callable[[NDArray[np.float32]], list[str]]


def exact_top_k(
    queries: NDArray[np.float32], vectors: NDArray[np.float32], k: int
) -> list[list[int]]:
    """Exact cosine nearest neighbours (rows of both are L2-normalised)."""
    scores = queries @ vectors.T
    top = np.argsort(-scores, axis=1, kind="stable")[:, :k]
    return [list(map(int, row)) for row in top]


def overlap(ranked: list[str], exact: list[str], k: int = K) -> float:
    return len(set(ranked[:k]) & set(exact[:k])) / k


def time_system(
    search: Search, queries: NDArray[np.float32], rounds: int = ROUNDS
) -> tuple[list[list[str]], list[float]]:
    """Results from a warm-up pass, then per-query latencies (ms) over `rounds` timed passes."""
    results = [search(q) for q in queries]
    latencies = []
    for _ in range(rounds):
        for q in queries:
            started = time.perf_counter()
            search(q)
            latencies.append((time.perf_counter() - started) * 1000)
    return results, latencies


def docker_memory() -> dict[str, str]:
    out = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{.Name}}|{{.MemUsage}}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    rows = dict(line.split("|", 1) for line in out.splitlines() if "|" in line)
    return {k: v for k, v in rows.items() if "qdrant" in k or "pgvector" in k}


def qdrant_disk_kb(collection: str) -> int:
    out = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "qdrant",
            "du",
            "-sk",
            f"/qdrant/storage/collections/{collection}",
        ],
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
    ).stdout
    return int(out.split()[0])


def qdrant_hnsw_copy(
    client: Any, name: str, chunk_ids: list[str], vectors: NDArray[np.float32]
) -> dict[str, float]:
    """A copy of the collection with HNSW forced on every segment; returns load/index seconds."""
    from qdrant_client.models import (
        Distance,
        HnswConfigDiff,
        OptimizersConfigDiff,
        PointStruct,
        VectorParams,
    )

    from retrieval.dense import UPSERT_BATCH, point_id

    if client.collection_exists(name):
        client.delete_collection(name)
    client.create_collection(
        name,
        vectors_config=VectorParams(size=int(vectors.shape[1]), distance=Distance.COSINE),
        # full_scan_threshold 10 KB (the minimum; segments here are ~4 MB): always use the graph;
        # indexing_threshold 1 KB: index every segment
        hnsw_config=HnswConfigDiff(
            m=HNSW_M, ef_construct=HNSW_EF_CONSTRUCT, full_scan_threshold=10
        ),
        optimizers_config=OptimizersConfigDiff(indexing_threshold=1),
    )
    started = time.perf_counter()
    for start in range(0, len(chunk_ids), UPSERT_BATCH):
        client.upsert(
            name,
            points=[
                PointStruct(id=point_id(c), vector=vectors[start + i].tolist(), payload={"id": c})
                for i, c in enumerate(chunk_ids[start : start + UPSERT_BATCH])
            ],
            wait=True,
        )
    loaded = time.perf_counter() - started
    while True:  # the optimizer builds HNSW in the background
        info = client.get_collection(name)
        if info.indexed_vectors_count >= len(chunk_ids) and str(info.status).endswith("green"):
            break
        if time.perf_counter() - started > 1800:
            raise TimeoutError(f"{name}: {info.indexed_vectors_count} of {len(chunk_ids)} indexed")
        time.sleep(1)
    return {
        "load_seconds": round(loaded, 1),
        "index_seconds": round(time.perf_counter() - started - loaded, 1),
    }


def main() -> int:
    from qdrant_client.models import SearchParams

    from retrieval import pgvector_store as pg
    from retrieval.contextual import variant
    from retrieval.dense import (
        SentenceTransformerEncoder,
        connect,
        document_vectors,
        load_chunks,
        load_config,
    )

    corpus, suffix = variant("contextual")
    cfg = load_config()
    cfg = cfg.model_copy(update={"collection": cfg.collection + suffix})
    chunks, chunks_sha256 = load_chunks(corpus)

    def not_cached(*_: Any) -> Any:
        raise RuntimeError(
            "contextual vectors are not cached; run `just index --variant contextual`"
        )

    vectors, meta = document_vectors(cfg, chunks, chunks_sha256, not_cached)
    chunk_ids = [c["id"] for c in chunks]
    items = [i for i in load_items() if i.answerable]
    encoder = SentenceTransformerEncoder(cfg, cfg.query_prefix)
    # golden questions are synthetic (no PHI); the encoder runs in-process (ADR-0001)
    queries = encoder.encode([i.question for i in items])
    exact = [[chunk_ids[j] for j in row] for row in exact_top_k(queries, vectors, K)]

    build: dict[str, Any] = {}
    client = connect()
    hnsw_name = cfg.collection + "_hnsw"
    build["qdrant_hnsw"] = qdrant_hnsw_copy(client, hnsw_name, chunk_ids, vectors)
    conn = pg.connect()
    build["pgvector"] = pg.load_table(conn, chunk_ids, vectors, str(meta["fingerprint"]))
    build["pgvector"]["index_seconds"] = round(pg.build_hnsw(conn, HNSW_M, HNSW_EF_CONSTRUCT), 1)
    deployed = client.get_collection(cfg.collection)
    build["qdrant"] = {
        "indexed_vectors": deployed.indexed_vectors_count,
        "segments": deployed.segments_count,
    }

    def qdrant_search(collection: str, ef: int | None = None) -> Search:
        params = SearchParams(hnsw_ef=ef) if ef else None

        def search(q: NDArray[np.float32]) -> list[str]:
            points = client.query_points(
                collection, query=q.tolist(), limit=K, with_payload=["id"], search_params=params
            ).points
            return [str((p.payload or {})["id"]) for p in points]

        return search

    def pg_search(retriever: pg.PgVectorRetriever) -> Search:
        return lambda q: [h.chunk_id for h in retriever.search_vector(q, K)]

    systems: dict[str, Search] = {"qdrant": qdrant_search(cfg.collection)}
    systems |= {f"qdrant_hnsw_ef{ef}": qdrant_search(hnsw_name, ef) for ef in EF_SEARCH}
    systems["pgvector_exact"] = pg_search(pg.PgVectorRetriever(conn, exact=True))
    systems |= {
        f"pgvector_hnsw_ef{ef}": pg_search(pg.PgVectorRetriever(conn, ef_search=ef))
        for ef in EF_SEARCH
    }

    rows: dict[str, dict[str, Any]] = {}
    for name, search in systems.items():
        results, latencies = time_system(search, queries)
        rows[name] = {
            "recall": [
                recall_at_k(r, set(i.gold_chunk_ids), K)
                for r, i in zip(results, items, strict=True)
            ],
            "ndcg": [
                ndcg_at_k(r, set(i.gold_chunk_ids), K) for r, i in zip(results, items, strict=True)
            ],
            "overlap": [overlap(r, e) for r, e in zip(results, exact, strict=True)],
            "p50": percentile(latencies, 0.5),
            "p95": percentile(latencies, 0.95),
        }
        print(
            f"{name}: recall@10 {np.mean(rows[name]['recall']):.3f}, p95 {rows[name]['p95']:.1f} ms"
        )

    sizes = conn.execute(
        "SELECT pg_relation_size('chunks_dense_ctx'), pg_relation_size('chunks_dense_ctx_hnsw'), "
        "pg_total_relation_size('chunks_dense_ctx')"
    ).fetchone()
    if sizes is None:
        raise RuntimeError("pgvector size query returned nothing")
    disk = {
        "pgvector_heap_mb": round(sizes[0] / 2**20, 1),  # vectors (3 KB each) live in TOAST
        "pgvector_hnsw_mb": round(sizes[1] / 2**20, 1),
        "pgvector_total_mb": round(sizes[2] / 2**20, 1),
        "qdrant_mb": round(qdrant_disk_kb(cfg.collection) / 1024, 1),
        "qdrant_hnsw_mb": round(qdrant_disk_kb(hnsw_name) / 1024, 1),
    }
    memory = docker_memory()
    client.delete_collection(hnsw_name)  # measurement copy only
    report = write_report(rows, build, disk, memory, len(items))
    print(report.read_text(encoding="utf-8"))
    return 0


def write_report(
    rows: dict[str, dict[str, Any]],
    build: dict[str, Any],
    disk: dict[str, float],
    memory: dict[str, str],
    n: int,
) -> Path:
    base = rows["qdrant"]
    lines = [
        "# Vector stores: Qdrant vs pgvector",
        "",
        f"{n} answerable golden questions; contextual chunk vectors (8,104 x 768, ModernBERT "
        "Embed), the same query vectors for every system; latency is store-only (query "
        "embedding excluded), "
        f"{ROUNDS} warm passes, client on the host, stores in Docker. HNSW m {HNSW_M}, "
        f"ef_construct {HNSW_EF_CONSTRUCT} in both. Overlap@10 = share of the exact 10 nearest "
        "neighbours returned. Paired 95% bootstrap vs `qdrant` (the deployed collection).",
        "",
        "| system | recall@10 | nDCG@10 | overlap@10 vs exact | p50 ms | p95 ms "
        "| recall@10 vs qdrant |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, r in rows.items():
        diff, low, high = paired_bootstrap(base["recall"], r["recall"])
        vs = "—" if name == "qdrant" else f"{diff:+.3f} [{low:+.3f}, {high:+.3f}]"
        lines.append(
            f"| {name} | {np.mean(r['recall']):.3f} | {np.mean(r['ndcg']):.3f} | "
            f"{np.mean(r['overlap']):.3f} | {r['p50']:.1f} | {r['p95']:.1f} | {vs} |"
        )
    lines += [
        "",
        "Build and footprint:",
        "",
        f"- deployed Qdrant collection: {build['qdrant']['indexed_vectors']} vectors HNSW-indexed "
        f"across {build['qdrant']['segments']} segments "
        "(below the indexing threshold: exact search)",
        f"- Qdrant HNSW copy: upsert {build['qdrant_hnsw']['load_seconds']} s, "
        f"index {build['qdrant_hnsw']['index_seconds']} s",
        "- pgvector: "
        + (
            f"COPY {build['pgvector']['load_seconds']} s"
            if "load_seconds" in build["pgvector"]
            else "table already loaded (COPY measured on the first run)"
        )
        + f", HNSW build {build['pgvector']['index_seconds']} s",
        f"- disk: pgvector total {disk['pgvector_total_mb']} MB "
        f"(HNSW {disk['pgvector_hnsw_mb']} MB, "
        f"heap {disk['pgvector_heap_mb']} MB, the rest TOAST + primary key); "
        f"Qdrant collection {disk['qdrant_mb']} MB, "
        f"HNSW copy {disk['qdrant_hnsw_mb']} MB",
        "- container memory after the run: "
        + ", ".join(f"{k} {v}" for k, v in sorted(memory.items()))
        + " (Qdrant holds all its collections: raw, contextual, late, HNSW copy)",
    ]
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / "vectorstore.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    raw = {name: {k: v for k, v in r.items()} for name, r in rows.items()}
    (REPORTS / "runs" / "vectorstore.json").write_text(
        json.dumps({"rows": raw, "build": build, "disk": disk, "memory": memory}, indent=1),
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    sys.exit(main())
