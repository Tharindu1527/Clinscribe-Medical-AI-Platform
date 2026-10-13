"""Mini retrieval fixture for the CI regression check (Phase 2 task 12).

CI has no corpus, no Qdrant and no model downloads, so this fixture carries everything the
first-stage retrievers need: 100 golden questions (FDA and PMC sources only: CC0 / CC BY text;
WHO chunks are CC BY-NC-SA and stay out of the repo), the chunks that matter for them (their gold
chunks plus the top 10 of the stored dense and BM25 runs), and precomputed ModernBERT Embed vectors
for chunks and questions (float16). `evaluate()` recomputes recall@10 and MRR@10 for dense (numpy
cosine), BM25 and hybrid RRF with the production code; `tests/unit/test_rag_regression.py` fails
when a metric drops below the committed threshold, so a change to tokenisation, BM25, RRF or the
metrics turns CI red. ColBERT and the query encoder need the models and are checked by
`just gate 2` instead.

  uv run python -m evals.rag.fixture     (rebuild; needs data/corpus and the cached dense vectors)
"""

import json
import random
import sys
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from evals.rag.metrics import recall_at_k, reciprocal_rank
from retrieval.bm25 import load_index
from retrieval.hybrid import rrf

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "rag_mini"
RUNS = ROOT / "evals" / "reports" / "rag" / "runs"
SOURCES = ("openfda", "pmc")  # licences that allow committing the text (see README)
PER_AREA = 20
SEED = 12
POOL_RUNS = ("dense", "bm25")
POOL_K = 10
K = 10
MARGIN = 0.01  # thresholds sit this far below the measured values (float16, library versions)


def load_fixture(path: Path = FIXTURE) -> tuple[list[dict[str, Any]], list[str], Any, Any]:
    questions = [
        json.loads(line)
        for line in (path / "questions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    chunk_ids = [
        json.loads(line)["id"]
        for line in (path / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    chunk_vectors = np.load(path / "chunk_vectors.npy").astype(np.float32)
    query_vectors = np.load(path / "query_vectors.npy").astype(np.float32)
    return questions, chunk_ids, chunk_vectors, query_vectors


def evaluate(path: Path = FIXTURE) -> dict[str, dict[str, float]]:
    """recall@10 and MRR@10 per first-stage system over the fixture, with the production code."""
    questions, chunk_ids, chunk_vectors, query_vectors = load_fixture(path)
    cfg = yaml.safe_load((ROOT / "config" / "retrieval.yaml").read_text(encoding="utf-8"))
    depth, rrf_k = cfg["hybrid"]["depth"], cfg["hybrid"]["rrf_k"]
    bm25 = load_index(path)
    scores = query_vectors @ chunk_vectors.T
    rankings: dict[str, list[list[str]]] = {"dense": [], "bm25": [], "hybrid": []}
    for q, row in zip(questions, scores, strict=True):
        dense = [chunk_ids[j] for j in np.argsort(-row, kind="stable")[:depth]]
        keyword = [h.chunk_id for h in bm25.top(q["question"], depth)]
        rankings["dense"].append(dense)
        rankings["bm25"].append(keyword)
        rankings["hybrid"].append([h.chunk_id for h in rrf([dense, keyword], k=rrf_k)])
    out = {}
    for system, ranked in rankings.items():
        pairs = list(zip(ranked, (set(q["gold_chunk_ids"]) for q in questions), strict=True))
        out[system] = {
            "recall@10": float(np.mean([recall_at_k(r, g, K) for r, g in pairs])),
            "mrr@10": float(np.mean([reciprocal_rank(r, g, K) for r, g in pairs])),
        }
    return out


def build(path: Path = FIXTURE) -> dict[str, dict[str, float]]:
    from evals.golden.golden import load_items
    from retrieval.dense import (
        SentenceTransformerEncoder,
        document_vectors,
        load_chunks,
        load_config,
    )

    items = [i for i in load_items() if i.answerable and i.source in SOURCES]
    rng = random.Random(SEED)
    picked = []
    for area in sorted({i.area for i in items}):
        pool = sorted((i for i in items if i.area == area), key=lambda i: i.id)
        picked += rng.sample(pool, min(PER_AREA, len(pool)))
    picked.sort(key=lambda i: i.id)

    chunks, chunks_sha256 = load_chunks()
    cfg = load_config()

    def not_cached(*_: Any) -> Any:
        raise RuntimeError("raw dense vectors are not cached; run `just index`")

    vectors, _ = document_vectors(cfg, chunks, chunks_sha256, not_cached)
    position = {c["id"]: n for n, c in enumerate(chunks)}
    by_id = {c["id"]: c for c in chunks}
    wanted = {c for i in picked for c in i.gold_chunk_ids}
    for run in POOL_RUNS:
        results = json.loads((RUNS / f"{run}.json").read_text(encoding="utf-8"))["results"]
        for item in picked:
            wanted.update(results[item.id]["ranked"][:POOL_K])
    keep = sorted(c for c in wanted if by_id[c]["source"] in SOURCES)

    path.mkdir(parents=True, exist_ok=True)
    fields = ("id", "source", "title", "section", "url", "license", "text")
    (path / "chunks.jsonl").write_text(
        "".join(json.dumps({f: by_id[c][f] for f in fields}) + "\n" for c in keep),
        encoding="utf-8",
        newline="\n",
    )
    (path / "questions.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "id": i.id,
                    "area": i.area,
                    "question": i.question,
                    "gold_chunk_ids": i.gold_chunk_ids,
                }
            )
            + "\n"
            for i in picked
        ),
        encoding="utf-8",
        newline="\n",
    )
    np.save(path / "chunk_vectors.npy", vectors[[position[c] for c in keep]].astype(np.float16))
    encoder = SentenceTransformerEncoder(cfg, cfg.query_prefix)
    # golden questions are synthetic (no PHI); the encoder runs in-process (ADR-0001)
    queries = encoder.encode([i.question for i in picked])
    np.save(path / "query_vectors.npy", queries.astype(np.float16))

    measured = evaluate(path)
    thresholds = {
        system: {m: round(v - MARGIN, 3) for m, v in metrics.items()}
        for system, metrics in measured.items()
    }
    (path / "thresholds.json").write_text(
        json.dumps({"measured": measured, "thresholds": thresholds}, indent=1) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return measured


def main() -> int:
    measured = build()
    print(json.dumps(measured, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
