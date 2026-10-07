"""Retrieval evaluation on the golden set: recall@k, MRR@10, nDCG@10 and query latency p50/p95.

  uv run python -m evals.rag.retrieval_eval                 dense baseline (`just eval rag`)
  uv run python -m evals.rag.retrieval_eval --system dense  run one system
  uv run python -m evals.rag.retrieval_eval --compare A B   paired bootstrap of saved runs A vs B

Each run saves its rankings to evals/reports/rag/runs/<system>.json, so later ablation steps are
compared question by question against the stored baseline without re-running it. Golden
questions are synthetic, so they are passed to the retriever as de-identified text.
"""

import argparse
import hashlib
import json
import sys
import time
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from evals.golden.golden import GOLDEN, GoldenItem, load_items
from evals.rag.metrics import (
    ndcg_at_k,
    paired_bootstrap,
    percentile,
    recall_at_k,
    reciprocal_rank,
)
from privacy.deid.types import DeidentifiedText, issue
from retrieval.dense import Hit

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "evals" / "reports" / "rag"
RUNS = REPORTS / "runs"
STORED_K = 20  # rankings kept per question (metrics use k <= 10)
METRICS = ("recall@1", "recall@5", "recall@10", "mrr@10", "ndcg@10")


class Retriever(Protocol):
    def search(self, query: DeidentifiedText, k: int = 10) -> list[Hit]: ...


System = Callable[[], tuple[Retriever, dict[str, Any]]]


def dense_system(variant: str = "raw") -> System:
    def build() -> tuple[Retriever, dict[str, Any]]:
        from retrieval.contextual import variant as corpus_variant
        from retrieval.dense import (
            DenseRetriever,
            SentenceTransformerEncoder,
            connect,
            load_chunks,
            load_config,
        )

        corpus, suffix = corpus_variant(variant)
        cfg = load_config()
        cfg = cfg.model_copy(update={"collection": cfg.collection + suffix})
        encoder = SentenceTransformerEncoder(cfg, cfg.query_prefix)
        meta = {
            "variant": variant,
            "model": cfg.model,
            "revision": cfg.revision,
            "collection": cfg.collection,
            "corpus_chunks_sha256": load_chunks(corpus)[1],
        }
        return DenseRetriever(cfg, connect(), encoder), meta

    return build


def bm25_system(variant: str = "raw") -> System:
    def build() -> tuple[Retriever, dict[str, Any]]:
        from retrieval.bm25 import BM25Retriever, load_index
        from retrieval.contextual import variant as corpus_variant
        from retrieval.dense import load_chunks

        corpus, _ = corpus_variant(variant)
        started = time.perf_counter()
        index = load_index(corpus)
        meta = {
            "variant": variant,
            "bm25": {
                "k1": index.k1,
                "b": index.b,
                "build_seconds": round(time.perf_counter() - started, 1),
            },
            "corpus_chunks_sha256": load_chunks(corpus)[1],
        }
        return BM25Retriever(index), meta

    return build


def hybrid_system(variant: str = "raw") -> System:
    def build() -> tuple[Retriever, dict[str, Any]]:
        import yaml

        from retrieval.hybrid import HybridRetriever

        dense, dense_meta = dense_system(variant)()
        bm25, bm25_meta = bm25_system(variant)()
        cfg = yaml.safe_load((ROOT / "config" / "retrieval.yaml").read_text(encoding="utf-8"))
        return HybridRetriever(dense, bm25, **cfg["hybrid"]), {
            **dense_meta,
            **bm25_meta,
            "hybrid": cfg["hybrid"],
        }

    return build


def reranked_system(first_stage: System, kind: str, variant: str = "raw") -> System:
    """First stage + reranker. The reranker reads the same corpus variant as the first stage."""

    def build() -> tuple[Retriever, dict[str, Any]]:
        from retrieval.colbert import ColBERTConfig, ColBERTEncoder, build_store
        from retrieval.contextual import variant as corpus_variant
        from retrieval.dense import load_chunks
        from retrieval.rerank import (
            ColBERTReranker,
            CrossEncoderReranker,
            RerankedRetriever,
            Reranker,
            rerank_config,
        )

        base, meta = first_stage()
        cfg = rerank_config()
        chunks, sha = load_chunks(corpus_variant(variant)[0])
        reranker: Reranker
        if kind == "ce":
            texts = {c["id"]: c["text"] for c in chunks}
            reranker = CrossEncoderReranker(texts, **cfg["cross_encoder"])
        else:
            col = ColBERTConfig.model_validate(cfg["colbert"])
            store, store_meta = build_store(col, chunks, sha, ColBERTEncoder)
            reranker = ColBERTReranker(ColBERTEncoder(col), store)
            meta = {**meta, "colbert_store": store_meta}
        reranker_cfg = cfg["cross_encoder"] if kind == "ce" else cfg["colbert"]
        meta = {**meta, "reranker": {"kind": kind, "depth": cfg["depth"], **reranker_cfg}}
        return RerankedRetriever(base, reranker, depth=cfg["depth"]), meta

    return build


SYSTEMS: dict[str, System] = {
    "dense": dense_system(),
    "bm25": bm25_system(),
    "hybrid": hybrid_system(),
    "dense_ce": reranked_system(dense_system(), "ce"),
    "hybrid_ce": reranked_system(hybrid_system(), "ce"),
    "dense_colbert": reranked_system(dense_system(), "colbert"),
    "hybrid_colbert": reranked_system(hybrid_system(), "colbert"),
    # ablation step 4: the same pipelines over the contextual-retrieval corpus
    "dense_ctx": dense_system("contextual"),
    "bm25_ctx": bm25_system("contextual"),
    "hybrid_ctx": hybrid_system("contextual"),
    "hybrid_colbert_ctx": reranked_system(hybrid_system("contextual"), "colbert", "contextual"),
    # ablation step 5: late chunking changes the dense vectors only (compared, not stacked)
    "dense_late": dense_system("late"),
    "hybrid_colbert_late": reranked_system(hybrid_system("late"), "colbert", "late"),
}


def per_question(ranked: Sequence[str], gold: set[str]) -> dict[str, float]:
    return {
        "recall@1": recall_at_k(ranked, gold, 1),
        "recall@5": recall_at_k(ranked, gold, 5),
        "recall@10": recall_at_k(ranked, gold, 10),
        "mrr@10": reciprocal_rank(ranked, gold, 10),
        "ndcg@10": ndcg_at_k(ranked, gold, 10),
    }


def run_system(name: str, items: list[GoldenItem]) -> dict[str, Any]:
    retriever, meta = SYSTEMS[name]()
    retriever.search(issue("warm-up query", "synthetic-golden-set"), k=1)  # model load, caches
    results: dict[str, Any] = {}
    for item in items:
        started = time.perf_counter()
        hits = retriever.search(issue(item.question, "synthetic-golden-set"), k=STORED_K)
        results[item.id] = {
            "ms": round((time.perf_counter() - started) * 1000, 1),
            "ranked": [h.chunk_id for h in hits],
            "scores": [round(h.score, 4) for h in hits],
        }
    return {
        "system": name,
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "golden_sha256": hashlib.sha256(GOLDEN.read_bytes()).hexdigest(),
        **meta,
        "results": results,
    }


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarise(run: dict[str, Any], items: list[GoldenItem]) -> dict[str, Any]:
    answerable = [i for i in items if i.answerable]
    scores = {
        i.id: per_question(run["results"][i.id]["ranked"], set(i.gold_chunk_ids))
        for i in answerable
    }
    groups: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for item in answerable:
        groups["area"][item.area].append(item.id)
        groups["source"][str(item.source)].append(item.id)
        groups["qtype"][item.qtype].append(item.id)
    breakdown = {
        field: {
            value: {"n": len(ids), **{m: mean([scores[i][m] for i in ids]) for m in METRICS}}
            for value, ids in sorted(members.items())
        }
        for field, members in groups.items()
    }
    latencies = [r["ms"] for r in run["results"].values()]
    top1 = {i.id: (run["results"][i.id]["scores"] or [0.0])[0] for i in items}
    return {
        "system": run["system"],
        "n_answerable": len(answerable),
        "overall": {m: mean([s[m] for s in scores.values()]) for m in METRICS},
        "breakdown": breakdown,
        "latency_ms": {"p50": percentile(latencies, 0.5), "p95": percentile(latencies, 0.95)},
        "top1_score_median": {
            "answerable": percentile([top1[i.id] for i in answerable], 0.5),
            "unanswerable": percentile([top1[i.id] for i in items if not i.answerable], 0.5),
        },
        "misses_at_10": [i.id for i in answerable if scores[i.id]["recall@10"] == 0.0],
        "per_question": scores,
    }


def _table(rows: dict[str, dict[str, float]], label: str) -> list[str]:
    lines = [f"| {label} | n | " + " | ".join(METRICS) + " |", "|---" * (len(METRICS) + 2) + "|"]
    for value, row in rows.items():
        cells = " | ".join(f"{row[m]:.3f}" for m in METRICS)
        lines.append(f"| {value} | {int(row['n'])} | {cells} |")
    return lines


def write_report(run: dict[str, Any], summary: dict[str, Any], items: list[GoldenItem]) -> Path:
    by_id = {i.id: i for i in items}
    overall = summary["overall"]
    lines = [
        f"# Retrieval evaluation: `{run['system']}`",
        "",
        f"Run {run['created']} · golden set `{run['golden_sha256'][:12]}` "
        f"({summary['n_answerable']} answerable questions) · corpus "
        f"`{run.get('corpus_chunks_sha256', '?')[:12]}`"
        + (f" · model `{run['model']}` @ `{run['revision'][:12]}`" if "model" in run else ""),
        "",
        "Recall@k is answer-level: a question counts as found when any chunk containing its quoted",
        "answer is in the top k. MRR@10 and nDCG@10 use every gold chunk (binary relevance).",
        "Gold chunks are those containing the exact quote, so a chunk giving the same answer in",
        "other words counts as a miss: these numbers are a lower bound for every system.",
        "",
        *_table({"all": {"n": summary["n_answerable"], **overall}}, "set"),
        "",
        f"Query latency (embed + search, warm, n={len(run['results'])}): "
        f"p50 {summary['latency_ms']['p50']:.0f} ms, p95 {summary['latency_ms']['p95']:.0f} ms.",
        "",
        "Median top-1 similarity: answerable "
        f"{summary['top1_score_median']['answerable']:.3f}, unanswerable "
        f"{summary['top1_score_median']['unanswerable']:.3f} (a first look at whether a score "
        "threshold could support abstention; not used yet).",
    ]
    for field in ("area", "source", "qtype"):
        lines += ["", f"## By {field}", "", *_table(summary["breakdown"][field], field)]
    lines += ["", f"## Missed at 10 ({len(summary['misses_at_10'])})", ""]
    lines += [
        f"- {i}: ({by_id[i].area}, {by_id[i].source}) {by_id[i].question}"
        for i in summary["misses_at_10"]
    ]
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"retrieval_{run['system']}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    summary_out = {k: v for k, v in summary.items() if k != "per_question"}
    (REPORTS / f"retrieval_{run['system']}.json").write_text(
        json.dumps(summary_out, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return path


def compare(baseline: str, candidate: str, items: list[GoldenItem]) -> Path:
    runs = {
        n: json.loads((RUNS / f"{n}.json").read_text(encoding="utf-8"))
        for n in (baseline, candidate)
    }
    if runs[baseline]["golden_sha256"] != runs[candidate]["golden_sha256"]:
        raise SystemExit("runs used different golden sets; re-run both")
    sums = {n: summarise(r, items) for n, r in runs.items()}
    ids = sorted(sums[baseline]["per_question"])
    lines = [
        f"# `{candidate}` vs `{baseline}`",
        "",
        f"Paired bootstrap over {len(ids)} answerable questions (10,000 resamples, seed 42).",
        "",
        "| metric | baseline | candidate | difference | 95% CI | better? |",
        "|---|---|---|---|---|---|",
    ]
    for metric in METRICS:
        a = [sums[baseline]["per_question"][i][metric] for i in ids]
        b = [sums[candidate]["per_question"][i][metric] for i in ids]
        diff, low, high = paired_bootstrap(a, b)
        verdict = "yes" if low > 0 else "no" if high < 0 else "not shown"
        lines.append(
            f"| {metric} | {mean(a):.3f} | {mean(b):.3f} | {diff:+.3f} | "
            f"[{low:+.3f}, {high:+.3f}] | {verdict} |"
        )
    # Which questions each system finds: complementary systems are candidates for fusion or for
    # a shared candidate pool even when neither wins on its own.
    lines += ["", "| found within | baseline only | candidate only | both | either |"]
    lines += ["|---|---|---|---|---|"]
    by_id = {i.id: i for i in items}
    for k in (10, STORED_K):
        found = {
            n: {
                i
                for i in ids
                if recall_at_k(runs[n]["results"][i]["ranked"], set(by_id[i].gold_chunk_ids), k)
            }
            for n in (baseline, candidate)
        }
        base, cand = found[baseline], found[candidate]
        lines.append(
            f"| top {k} | {len(base - cand)} | {len(cand - base)} | {len(base & cand)} | "
            f"{len(base | cand)} ({len(base | cand) / len(ids):.3f}) |"
        )
    path = REPORTS / f"compare_{candidate}_vs_{baseline}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Retrieval evaluation on the golden set")
    parser.add_argument("--system", default="dense", choices=sorted(SYSTEMS))
    parser.add_argument("--compare", nargs=2, metavar=("BASELINE", "CANDIDATE"))
    args = parser.parse_args(argv)
    items = load_items()
    if args.compare:
        baseline, candidate = args.compare
        print(compare(baseline, candidate, items).read_text(encoding="utf-8"))
        return 0
    run = run_system(args.system, items)
    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / f"{args.system}.json").write_text(json.dumps(run) + "\n", encoding="utf-8")
    summary = summarise(run, items)
    path = write_report(run, summary, items)
    overall = summary["overall"]
    print(f"{args.system}: " + ", ".join(f"{m} {overall[m]:.3f}" for m in METRICS))
    print(f"report: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
