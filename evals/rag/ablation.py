"""Phase 2 ablation report and gate criteria (SPEC sections 11-12, task 12).

Reads the stored retrieval runs (`evals/reports/rag/runs/`) and answer rows
(`evals/reports/rag/answers/`); makes no model or LLM calls. Every step is compared with the
system it was added to, on the same questions, with a 95% paired bootstrap interval.

Phase 2 gate (SPEC section 12, wording decided 2026-10-13): the chosen pipeline beats dense-only on
recall@10 (interval above 0) and on answer correctness (interval above 0), and its faithfulness is
not worse by more than NON_INFERIORITY (interval lower bound above -0.05). Faithfulness sits near
0.94 for every pipeline because the generator abstains rather than guesses, so "shown better" was
replaced by non-inferiority.

  uv run python -m evals.rag.ablation          report -> evals/reports/rag/ablation.md
  uv run python -m evals.rag.ablation --gate   exit 1 if a gate criterion fails
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from evals.golden.golden import GOLDEN, load_items
from evals.rag.answer_eval import load_rows
from evals.rag.metrics import ndcg_at_k, paired_bootstrap, percentile, recall_at_k, reciprocal_rank

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "evals" / "reports" / "rag"
CHOSEN = "hybrid_colbert_ctx"
BASELINE = "dense"
NON_INFERIORITY = 0.05

# (step, what was added, baseline system, candidate system, outcome)
STEPS = [
    ("2", "BM25 + RRF (hybrid)", "dense", "hybrid", "kept: complementary pool for the reranker"),
    ("3a", "cross-encoder rerank", "hybrid", "hybrid_ce", "rejected: no gain, ~3 s/query"),
    ("3b", "ColBERT rerank", "hybrid", "hybrid_colbert", "kept (ADR-0006)"),
    ("4", "contextual retrieval", "hybrid_colbert", "hybrid_colbert_ctx", "kept"),
    ("5", "late chunking (instead of 4)", "hybrid_colbert_ctx", "hybrid_colbert_late", "rejected"),
    ("6", "GraphRAG candidates", "hybrid_colbert_ctx", "graph_ctx", "facts kept, candidates not"),
    (
        "re-check",
        "BM25 removed from the chosen pipeline",
        "hybrid_colbert_ctx",
        "dense_colbert_ctx",
        "BM25 kept (ADR-0006 re-check)",
    ),
    ("chosen", "chosen pipeline vs dense-only", BASELINE, CHOSEN, "gate"),
]
METRICS = ("recall@10", "mrr@10", "ndcg@10")


def load_run(system: str) -> dict[str, Any]:
    path = REPORTS / "runs" / f"{system}.json"
    run: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return run


def per_question(system: str) -> dict[str, dict[str, float]]:
    run = load_run(system)
    current = hashlib.sha256(GOLDEN.read_bytes()).hexdigest()
    if run["golden_sha256"] != current:
        raise ValueError(f"{system}: run is for another golden-set version; rerun just eval rag")
    out = {}
    for item in load_items():
        if not item.answerable:
            continue
        ranked, gold = run["results"][item.id]["ranked"], set(item.gold_chunk_ids)
        out[item.id] = {
            "recall@10": recall_at_k(ranked, gold, 10),
            "mrr@10": reciprocal_rank(ranked, gold, 10),
            "ndcg@10": ndcg_at_k(ranked, gold, 10),
        }
    return out


def latency(system: str) -> tuple[float, float]:
    ms = [r["ms"] for r in load_run(system)["results"].values()]
    return percentile(ms, 0.5), percentile(ms, 0.95)


def compare(
    baseline: dict[str, dict[str, float]], candidate: dict[str, dict[str, float]], metric: str
) -> tuple[float, float, float, float, float]:
    ids = sorted(baseline)
    a = [baseline[i][metric] for i in ids]
    b = [candidate[i][metric] for i in ids]
    diff, low, high = paired_bootstrap(a, b)
    return sum(a) / len(a), sum(b) / len(b), diff, low, high


def answer_pairs(baseline: str, candidate: str, metric: str) -> tuple[list[float], list[float]]:
    rows = {s: load_rows(s) for s in (baseline, candidate)}
    ids = sorted(set(rows[baseline]) & set(rows[candidate]))
    pairs = [
        (rows[baseline][i]["metrics"][metric], rows[candidate][i]["metrics"][metric])
        for i in ids
        if metric in rows[baseline][i]["metrics"] and metric in rows[candidate][i]["metrics"]
    ]
    return [p[0] for p in pairs], [p[1] for p in pairs]


def gate_checks() -> list[tuple[str, bool, str]]:
    """(criterion, passed, evidence) for the Phase 2 gate."""
    _, _, diff, low, high = compare(per_question(BASELINE), per_question(CHOSEN), "recall@10")
    checks = [
        (
            "recall@10: chosen beats dense-only",
            low > 0,
            f"{diff:+.3f} [{low:+.3f}, {high:+.3f}]",
        )
    ]
    a, b = answer_pairs(BASELINE, CHOSEN, "correctness")
    diff, low, high = paired_bootstrap(a, b)
    checks.append(
        (
            "answer correctness: chosen beats dense-only",
            low > 0,
            f"{diff:+.3f} [{low:+.3f}, {high:+.3f}], n {len(a)}",
        )
    )
    a, b = answer_pairs(BASELINE, CHOSEN, "faithfulness")
    diff, low, high = paired_bootstrap(a, b)
    checks.append(
        (
            f"faithfulness: chosen not worse than dense-only by > {NON_INFERIORITY}",
            low > -NON_INFERIORITY,
            f"{diff:+.3f} [{low:+.3f}, {high:+.3f}], n {len(a)}",
        )
    )
    return checks


def write_report() -> Path:
    cache: dict[str, dict[str, dict[str, float]]] = {}

    def pq(system: str) -> dict[str, dict[str, float]]:
        if system not in cache:
            cache[system] = per_question(system)
        return cache[system]

    n = len(pq(BASELINE))
    base = {m: sum(q[m] for q in pq(BASELINE).values()) / n for m in METRICS}
    p50, p95 = latency(BASELINE)
    lines = [
        "# Phase 2 ablation report",
        "",
        f"{n} answerable golden questions (golden set v1). Recall is answer-level and",
        "quote-based: a chunk that gives the same answer in other words counts as a miss (2 of 6",
        "sampled misses in task 4), so every recall figure is a lower bound. Each step is compared",
        "with the system it was added to; 95% paired bootstrap intervals. Latency is per query on",
        "CPU (query embedding, retrieval and reranking), p50/p95, all systems re-timed back to",
        "back on 2026-10-13.",
        "",
        f"Step 1, dense-only baseline: recall@10 {base['recall@10']:.3f}, MRR@10 "
        f"{base['mrr@10']:.3f}, nDCG@10 {base['ndcg@10']:.3f}; p50 {p50:.0f} ms, p95 {p95:.0f} ms.",
        "",
        "| step | added | vs | recall@10 | difference [95% CI] | MRR@10 difference | "
        "nDCG@10 difference | p50 / p95 ms | outcome |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for step, added, baseline, candidate, outcome in STEPS:
        cells = []
        recall = compare(pq(baseline), pq(candidate), "recall@10")
        for metric in ("mrr@10", "ndcg@10"):
            _, _, diff, low, high = compare(pq(baseline), pq(candidate), metric)
            cells.append(f"{diff:+.3f} [{low:+.3f}, {high:+.3f}]")
        c50, c95 = latency(candidate)
        lines.append(
            f"| {step} | {added} (`{candidate}`) | `{baseline}` | {recall[1]:.3f} | "
            f"{recall[2]:+.3f} [{recall[3]:+.3f}, {recall[4]:+.3f}] | {cells[0]} | {cells[1]} | "
            f"{c50:.0f} / {c95:.0f} | {outcome} |"
        )
    lines += [
        "",
        "Not in this table: step 7 (adaptive routing) and Self-RAG / CRAG move to Phase 3 (they",
        "need the agent loop). Vector store: ADR-0007 (Qdrant kept; pgvector measured).",
        "",
        "## Answers (60-question stratified subset, task 10)",
        "",
        "Generator Groq gpt-oss-20b, judge gpt-oss-120b; faithfulness and citation precision on",
        "questions both systems answered, correctness on all answerable questions.",
        "",
        "| candidate vs dense | correctness | faithfulness | citation precision |",
        "|---|---|---|---|",
    ]
    for candidate in ("hybrid_colbert", CHOSEN):
        cells = []
        for metric in ("correctness", "faithfulness", "citation_precision"):
            a, b = answer_pairs(BASELINE, candidate, metric)
            diff, low, high = paired_bootstrap(a, b)
            cells.append(
                f"{sum(b) / len(b):.3f} ({diff:+.3f} [{low:+.3f}, {high:+.3f}], n {len(a)})"
            )
        lines.append(f"| `{candidate}` | " + " | ".join(cells) + " |")
    lines += [
        "",
        "Graph-only check (10 Major DDInter pairs no chunk names together): text + DDInter facts",
        "answered 10/10 with faithfulness 0.95, text only 4/10 with 0.62 "
        "(`answers_graph_facts.md`).",
        "",
        "## Phase 2 gate",
        "",
        "| criterion | evidence | result |",
        "|---|---|---|",
        *[
            f"| {name} | {evidence} | {'PASS' if ok else 'FAIL'} |"
            for name, ok, evidence in gate_checks()
        ],
    ]
    path = REPORTS / "ablation.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 2 ablation report and gate criteria")
    parser.add_argument("--gate", action="store_true", help="check the gate criteria only")
    args = parser.parse_args(argv)
    if args.gate:
        checks = gate_checks()
        for name, ok, evidence in checks:
            print(f"{'PASS' if ok else 'FAIL'}  {name}: {evidence}")
        return 0 if all(ok for _, ok, _ in checks) else 1
    print(write_report().read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
