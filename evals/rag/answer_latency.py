"""Answer-call latency and output tokens for two answer prompts on the same passages, uncached
(ADR-0025: the reasoning-effort trial). Quality comes from `evals/rag/answer_eval.py`; this
script only times the generator, through the gateway, with no replay cache.

For the first N questions of the answer evaluation's subset, the chosen pipeline's top-5
passages go to the production prompt and to the trial prompt, alternating which goes first, so
a slow minute at the provider falls on both. Two things made earlier runs time the wrong thing:
- fallbacks: a rate-limited call was answered by the local model (half the calls of the first
  run); they are off here, so a rate limit is a wait, never another model;
- the gateway's own retries: LiteLLM waits out a per-minute limit inside the request
  (num_retries), so a 1 s answer was timed at up to 60 s. An answer whose call the gateway
  retried is measured again after a pause, and calls are spaced to stay under the limit.
Rows are kept, so a run stopped by the daily budget resumes.

A second table needs no calls: the evaluation's cached completions keep the latency of the
uncached call that recorded them, so every stored answer row of both prompts is timed too
(recorded on different days, retries not recorded before 2026-10-27; the first table is the
paired measurement).

  uv run python -m evals.rag.answer_latency [--n 10] [--prompt prompts/experiments/...yaml]
Writes evals/reports/rag/answer_latency.md (rows in answer_latency.jsonl).
"""

import argparse
import json
import random
import statistics
import sys
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from config.settings import Settings
from evals.golden.golden import GoldenItem, load_items
from evals.rag.answer_eval import (
    CACHE,
    OUT,
    ROOT,
    RUNS,
    TOP_K,
    BudgetExhaustedError,
    PatientClient,
    stratified_subset,
)
from evals.rag.metrics import percentile
from llmops.gateway.client import ChatMessage, Completion, GatewayClient, ReplayCache, alias_for
from privacy.deid.types import issue
from retrieval.generate import AnswerGenerator, AnswerSpec, Chat, load_spec

REPORT = ROOT / "evals" / "reports" / "rag" / "answer_latency.md"
ROWS = ROOT / "evals" / "reports" / "rag" / "answer_latency.jsonl"
TRIAL = ROOT / "prompts" / "experiments" / "answer_cited_low.yaml"
SYSTEM = "hybrid_colbert_ctx"
TRIAL_ROWS = "hybrid_colbert_ctx_low"  # answer_eval --name of the quality trial
METHOD = 2  # rows timed before the retry check (method 1) are not reused
PACE_S = 20.0  # between calls: ~2.2k tokens each against Groq's free 8k tokens per minute
ATTEMPTS = 4  # measurements of one answer before it is reported as retried


class Timed:
    """The generator's chat client, keeping each call's latency, output tokens and model."""

    def __init__(self, inner: Chat) -> None:
        self.inner = inner
        self.calls: list[Completion] = []

    def complete(self, model: str, messages: Sequence[ChatMessage], **kwargs: Any) -> Completion:
        reply = self.inner.complete(model, messages, **kwargs)
        self.calls.append(reply)
        return reply


def timing(calls: Sequence[Completion]) -> dict[str, Any]:
    return {
        "latency_ms": round(sum(c.latency_ms for c in calls), 1),
        "output_tokens": sum(c.output_tokens for c in calls),
        "calls": len(calls),
        "models": sorted({c.model for c in calls}),
        "retries": sum(c.retries for c in calls),
    }


def measure(client: Chat, spec: AnswerSpec, question: str, chunks: Sequence[Any]) -> dict[str, Any]:
    """One answer's calls, measured again while the gateway had to retry one of them."""
    for attempt in range(1, ATTEMPTS + 1):
        time.sleep(PACE_S)
        timed = Timed(client)
        AnswerGenerator(timed, alias_for(spec.task), spec).answer(
            issue(question, "synthetic-golden-set"), chunks
        )
        result = {**timing(timed.calls), "attempts": attempt}
        if result["retries"] == 0:
            break
        print(
            f"  gateway retried ({result['latency_ms']:,.0f} ms); measuring again", file=sys.stderr
        )
        time.sleep(60)
    return result


def median_difference(
    baseline: Sequence[float], candidate: Sequence[float], n: int = 10_000, seed: int = 42
) -> tuple[float, float, float]:
    """Median of (candidate - baseline) per question and its 95% paired bootstrap interval (a
    median, because one slow call would move a mean by seconds)."""
    diffs = [c - b for b, c in zip(baseline, candidate, strict=True)]
    rng = random.Random(seed)
    medians = sorted(statistics.median(rng.choices(diffs, k=len(diffs))) for _ in range(n))
    return statistics.median(diffs), medians[int(0.025 * n)], medians[int(0.975 * n) - 1]


def recorded(
    name: str, spec: AnswerSpec, items: Mapping[str, GoldenItem], corpus: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    """Each stored answer row's generator calls, replayed from the cache (no network)."""
    path = OUT / f"{name}.jsonl"
    if not path.exists():
        return {}
    settings = Settings()
    timed = Timed(
        GatewayClient(
            settings.gateway_url, settings.litellm_app_key, cache=ReplayCache(CACHE, "replay")
        )
    )
    generator = AnswerGenerator(timed, alias_for(spec.task), spec)
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        timed.calls.clear()
        generator.answer(
            issue(items[row["id"]].question, "synthetic-golden-set"),
            [corpus[c] for c in row["chunk_ids"]],
        )
        out[row["id"]] = timing(timed.calls)
    return out


def table(
    results: Mapping[str, Sequence[Mapping[str, Any]]], specs: Mapping[str, AnswerSpec]
) -> list[str]:
    lines = [
        "| prompt | reasoning effort | n | latency p50 ms | latency p95 ms | output tokens, median "
        "| calls | served by |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, spec in specs.items():
        rows = results[name]
        latency = [r["latency_ms"] for r in rows]
        served = Counter(m for r in rows for m in r["models"])
        lines.append(
            f"| {spec.id}@v{spec.version} | {spec.reasoning_effort or 'default'} | {len(rows)} | "
            f"{percentile(latency, 0.5):,.0f} | {percentile(latency, 0.95):,.0f} | "
            f"{statistics.median(r['output_tokens'] for r in rows):.0f} | "
            f"{sum(r['calls'] for r in rows)} | "
            + ", ".join(f"`{m}` {k}" for m, k in served.most_common())
            + " |"
        )
    return lines


def paired_line(a: Sequence[float], b: Sequence[float]) -> str:
    diff, low, high = median_difference(a, b)
    faster = sum(y < x for x, y in zip(a, b, strict=True))
    return (
        f"Paired over {len(a)} questions: median difference (trial − production) "
        f"**{diff:+,.0f} ms**, 95% bootstrap interval [{low:+,.0f}, {high:+,.0f}]; "
        f"the trial was faster on {faster} of {len(a)}."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=10)
    parser.add_argument("--prompt", type=Path, default=TRIAL)
    args = parser.parse_args(argv)
    settings = Settings()
    gateway = GatewayClient(  # no cache: every call reaches the provider
        settings.gateway_url, settings.litellm_app_key, timeout=180.0, trace=False
    )
    client = PatientClient(gateway, fallbacks=False)
    specs = {"production": load_spec(), "trial": load_spec(args.prompt)}
    items = {i.id: i for i in load_items()}
    rankings = json.loads((RUNS / f"{SYSTEM}.json").read_text(encoding="utf-8"))["results"]
    corpus = {
        (c := json.loads(line))["id"]: c
        for line in (ROOT / "data/corpus/chunks.jsonl").read_text(encoding="utf-8").splitlines()
    }
    versions: dict[str, Any] = {k: f"{s.id}@v{s.version}" for k, s in specs.items()}
    versions["method"] = METHOD
    done = {}
    if ROWS.exists():
        for line in ROWS.read_text(encoding="utf-8").splitlines():
            saved = json.loads(line)
            if saved["versions"] == versions:
                done[saved["id"]] = saved
    subset = stratified_subset(load_items())[: args.n]
    try:
        with ROWS.open("a", encoding="utf-8", newline="\n") as out:
            for n, item in enumerate(subset):
                if item.id in done:
                    continue
                chunks = [corpus[c] for c in rankings[item.id]["ranked"][:TOP_K]]
                row: dict[str, Any] = {"id": item.id, "versions": versions}
                for name in list(specs) if n % 2 == 0 else list(reversed(specs)):
                    row[name] = measure(client, specs[name], item.question, chunks)
                out.write(json.dumps(row) + "\n")
                out.flush()
                done[item.id] = row
                print(item.id, {k: row[k]["latency_ms"] for k in specs}, file=sys.stderr)
    except BudgetExhaustedError as exc:
        print(f"stopped: {exc}. Rows are kept; rerun later to resume ({len(done)} done).")
        return 2

    clean = [done[i.id] for i in subset if not any(done[i.id][k]["retries"] for k in specs)]
    repeats = sum(done[i.id][k]["attempts"] - 1 for i in subset for k in specs)
    lines = [
        "# Answer-call latency: production prompt vs trial (ADR-0025)",
        "",
        f"Generated by `evals/rag/answer_latency.py`. **Paired, uncached:** the first {args.n}",
        f"questions of the answer evaluation's subset, the `{SYSTEM}` top-{TOP_K} passages, sent",
        f"through the gateway to `{alias_for(specs['production'].task)}` with both prompts (order",
        f"alternating), fallbacks off, calls spaced by {PACE_S:.0f} s. Latency is the client's",
        "time for the answer's calls (a validation retry counts). An answer the gateway had to",
        "retry (a rate-limit wait inside the request) was measured again; a question where one",
        f"stayed retried after {ATTEMPTS} attempts is left out: {args.n - len(clean)} of",
        f"{args.n}. Measurements repeated: {repeats}.",
        "",
        *table({k: [r[k] for r in clean] for k in specs}, specs),
        "",
        paired_line(
            [r["production"]["latency_ms"] for r in clean],
            [r["trial"]["latency_ms"] for r in clean],
        ),
    ]
    stored = {
        "production": recorded(SYSTEM, specs["production"], items, corpus),
        "trial": recorded(TRIAL_ROWS, specs["trial"], items, corpus),
    }
    if stored["trial"]:
        common = [k for k in stored["trial"] if k in stored["production"]]
        lines += [
            "",
            "**Recorded with the quality evaluation** (no new calls): the latency each cached",
            "completion kept from the uncached call that recorded it. Production rows were",
            "recorded on 2026-10-09, trial rows from 2026-10-27, so provider load differs, and",
            "the gateway's retries were not recorded then: a few of these include its waits.",
            "Read the medians.",
            "",
            *table({k: list(v.values()) for k, v in stored.items()}, specs),
            "",
            paired_line(
                [stored["production"][k]["latency_ms"] for k in common],
                [stored["trial"][k]["latency_ms"] for k in common],
            ),
        ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
