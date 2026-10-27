"""Fast path vs agentic loop, and the router between them (SPEC section 6: "judged by how often it
picks the cheaper path without losing answer quality"; section 11 ablation step 7).

Each question goes through the real Ask graph twice, once forced down each path: guidelines-mcp
retrieval and druggraph-mcp facts as in production, the production models through the gateway,
the same guardrails. Every answer is judged as in the Phase 2 answer evaluation
(prompts/judge_citations.yaml: correctness against the golden quote, faithfulness, citation
precision), against the evidence that path gave the model. Then three policies are compared on
the same questions: always fast, always agentic, and the router's choice.

Questions: every answerable interaction question (what the agentic path is for), plus a seeded
sample of 10 other answerable questions the router sends agentic and 10 it sends fast. Model
calls are cached and rows saved as they come, so a run stopped by the free tier's daily budget
resumes where it stopped.

  uv run python -m evals.agents.router_eval [--limit N] [--report]
      (needs `just up rag`; resumable; --report rewrites the report from the saved rows)
Writes evals/reports/agents/router_answers.jsonl and router_quality.md.
"""

import json
import random
import statistics
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal

import yaml

from agents.graph import Agents, route_question
from agents.tools import McpTools
from config.settings import Settings
from evals.golden.golden import GoldenItem, load_items
from evals.rag.answer_eval import (
    CACHE,
    JUDGE_FILE,
    BudgetExhaustedError,
    PatientClient,
    judge_messages,
    metrics,
    parse_judgment,
)
from evals.rag.metrics import paired_bootstrap
from llmops.gateway.client import ChatMessage, Completion, GatewayClient, ReplayCache, alias_for
from privacy.deid.types import issue
from retrieval.generate import CitedAnswer, CitedSentence, source_block

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "evals" / "reports" / "agents"
ROWS = REPORTS / "router_answers.jsonl"
REPORT = REPORTS / "router_quality.md"
SEED = 7
PER_GROUP = 10
Path_ = Literal["fast", "agentic"]
PATHS: tuple[Path_, Path_] = ("fast", "agentic")


class Counting:
    """The graph's chat client, counting model calls and tokens per question."""

    def __init__(self, inner: PatientClient) -> None:
        self.inner = inner
        self.calls: list[tuple[str, int, int]] = []

    def complete(self, model: str, messages: Sequence[ChatMessage], **kwargs: Any) -> Completion:
        reply = self.inner.complete(model, messages, **kwargs)
        self.calls.append((model, reply.input_tokens, reply.output_tokens))
        return reply


def forced(path: Path_) -> Callable[[str], Path_]:
    def route(_question: str) -> Path_:
        return path

    return route


def questions(items: Sequence[GoldenItem]) -> list[tuple[GoldenItem, str]]:
    answerable = sorted((i for i in items if i.answerable), key=lambda i: i.id)
    interaction = [i for i in answerable if i.qtype == "interaction"]
    others = [i for i in answerable if i.qtype != "interaction"]
    rng = random.Random(SEED)
    to_agentic = [i for i in others if route_question(i.question) == "agentic"]
    to_fast = [i for i in others if route_question(i.question) == "fast"]
    picked = [(i, "interaction") for i in interaction]
    picked += [(i, "other, routed agentic") for i in rng.sample(to_agentic, PER_GROUP)]
    picked += [(i, "other, routed fast") for i in rng.sample(to_fast, PER_GROUP)]
    return picked


def judge(
    client: PatientClient, spec: dict[str, Any], item: GoldenItem, out: dict[str, Any]
) -> dict[str, Any]:
    chunks = [
        {"id": e["chunk_id"], "title": e["title"], "section": e["section"], "text": e["text"]}
        for e in out.get("evidence", [])
    ]
    raw = out["answer"]
    answer = CitedAnswer(
        abstained=raw["abstained"],
        sentences=[
            CitedSentence(text=s["text"], chunk_ids=s["citations"]) for s in raw["sentences"]
        ],
        prompt=raw["prompt_version"],
        model=raw["model"],
        attempts=1,
    )
    judgment, error = None, None
    if not answer.abstained:
        _, labels = source_block(chunks)
        messages = judge_messages(spec, item, chunks, answer)
        for _ in range(2):  # one retry with the error attached, as in the answer evaluation
            reply = client.complete(
                alias_for(spec["task"]),
                messages,
                temperature=0.0,
                max_tokens=spec["max_tokens"],
            )
            try:
                judgment = parse_judgment(reply.text, answer, labels)
                break
            except (ValueError, json.JSONDecodeError) as exc:
                error = str(exc)
                note = f"Invalid reply: {error}. Reply with the JSON object only."
                messages = [*messages, ChatMessage("user", issue(note, "eval-harness"))]
    return {"metrics": metrics(item, answer, judgment), "judge_error": None if judgment else error}


def run_all(limit: int | None = None) -> int:
    settings = Settings()
    gateway = GatewayClient(
        settings.gateway_url,
        settings.litellm_app_key,
        cache=ReplayCache(CACHE, "record"),
        timeout=300,
        trace=False,
    )
    client = PatientClient(gateway)
    tools = McpTools(settings.guidelines_mcp_url, settings.druggraph_mcp_url, settings.fhir_mcp_url)
    spec = yaml.safe_load(JUDGE_FILE.read_text(encoding="utf-8"))
    done = {(r["id"], r["path"]) for r in load_rows()}
    REPORTS.mkdir(parents=True, exist_ok=True)
    try:
        for item, group in questions(load_items())[:limit]:
            for path in PATHS:
                if (item.id, path) in done:
                    continue
                counter = Counting(client)
                graph = Agents(counter, tools, route=forced(path)).build()
                started = time.perf_counter()
                out = graph.invoke(
                    {"mode": "ask", "encounter_id": f"router-{item.id}", "question": item.question}
                )
                seconds = time.perf_counter() - started
                row = {
                    "id": item.id,
                    "group": group,
                    "router_choice": route_question(item.question),
                    "path": path,
                    "seconds": round(seconds, 2),
                    "model_calls": len(counter.calls),
                    "tokens": sum(i + o for _, i, o in counter.calls),
                    **judge(client, spec, item, out),
                }
                with ROWS.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row) + "\n")
                print(item.id, path, json.dumps(row["metrics"]), file=sys.stderr)
    except BudgetExhaustedError as exc:
        print(f"stopped: {exc}. Rerun later: rows and model calls are kept.", file=sys.stderr)
        write_report()
        return 2
    write_report()
    return 0


def load_rows() -> list[dict[str, Any]]:
    if not ROWS.exists():
        return []
    return [json.loads(line) for line in ROWS.read_text(encoding="utf-8").splitlines() if line]


def _mean(values: Sequence[float | None], digits: int = 3) -> str:
    present = [v for v in values if v is not None]
    return f"{statistics.mean(present):.{digits}f}" if present else "-"


def _ci(base: list[float], cand: list[float]) -> str:
    if len(base) < 2:
        return "-"
    diff, low, high = paired_bootstrap(base, cand)
    return f"{diff:+.3f} [{low:+.3f}, {high:+.3f}]"


def write_report() -> None:
    rows = load_rows()
    by_key = {(r["id"], r["path"]): r for r in rows}
    ids = sorted({r["id"] for r in rows if all((r["id"], p) in by_key for p in PATHS)})
    pair = {i: {p: by_key[(i, p)] for p in PATHS} for i in ids}

    def score(row: dict[str, Any]) -> float:
        return float(row["metrics"].get("correctness", 0.0))

    def policy(name: str) -> list[dict[str, Any]]:
        chosen: list[dict[str, Any]] = []
        for i in ids:
            if name == "router":
                pick: Path_ = "agentic" if pair[i]["fast"]["router_choice"] == "agentic" else "fast"
            else:
                pick = "agentic" if name == "agentic" else "fast"
            chosen.append(pair[i][pick])
        return chosen

    lines = [
        "# Fast path vs agentic loop, and the router (SPEC section 6; ablation step 7)",
        "",
        "Generated by `evals/agents/router_eval.py`: each question through the real Ask graph,",
        "forced down each path (production retrieval, drug facts, models and guardrails), every",
        "answer judged by `judge_citations` against the evidence that path gave the model.",
        f"Questions with both paths done: {len(ids)}.",
        "",
        "| policy | correctness | false abstentions | faithfulness | citation precision "
        "| model calls / question | tokens / question |",
        "|---|---|---|---|---|---|---|",
    ]
    for name in ("fast", "agentic", "router"):
        chosen = policy(name)
        m = [r["metrics"] for r in chosen]
        lines.append(f"| always {name} | " if name != "router" else "| router's choice | ")
        lines[-1] += (
            f"{_mean([score(r) for r in chosen])} | "
            f"{sum(bool(x.get('false_abstain')) for x in m)} of {len(m)} | "
            f"{_mean([x.get('faithfulness') for x in m])} | "
            f"{_mean([x.get('citation_precision') for x in m])} | "
            f"{_mean([r['model_calls'] for r in chosen], 1)} | "
            f"{_mean([r['tokens'] for r in chosen], 0)} |"
        )
    fast = [score(r) for r in policy("fast")]
    agentic = [score(r) for r in policy("agentic")]
    router = [score(r) for r in policy("router")]
    lines += [
        "",
        "Paired differences in correctness (95% bootstrap interval):",
        "",
        f"- agentic minus fast, all questions: {_ci(fast, agentic)}",
        f"- router minus always agentic: {_ci(agentic, router)}",
        f"- router minus always fast: {_ci(fast, router)}",
        "",
        "| group | questions | router sends agentic | correctness fast | correctness agentic "
        "| agentic minus fast |",
        "|---|---|---|---|---|---|",
    ]
    for group in ("interaction", "other, routed agentic", "other, routed fast"):
        members = [i for i in ids if pair[i]["fast"]["group"] == group]
        if not members:
            continue
        f_s = [score(pair[i]["fast"]) for i in members]
        a_s = [score(pair[i]["agentic"]) for i in members]
        sent = sum(pair[i]["fast"]["router_choice"] == "agentic" for i in members)
        lines.append(
            f"| {group} | {len(members)} | {sent} | {_mean(f_s)} | {_mean(a_s)} | {_ci(f_s, a_s)} |"
        )
    lines += [
        "",
        "Faithfulness and citation precision, paired on the questions both answered (95% "
        "bootstrap interval):",
        "",
    ]
    for metric in ("faithfulness", "citation_precision"):
        for label, base_name, cand_name in (
            ("agentic minus fast", "fast", "agentic"),
            ("router minus always agentic", "agentic", "router"),
        ):
            pairs = [
                (b["metrics"][metric], c["metrics"][metric])
                for b, c in zip(policy(base_name), policy(cand_name), strict=True)
                if metric in b["metrics"] and metric in c["metrics"]
            ]
            lines.append(
                f"- {metric.replace('_', ' ')}, {label}: "
                f"{_ci([b for b, _ in pairs], [c for _, c in pairs])} (n {len(pairs)})"
            )
    # the subset over-weights agentic questions; on the whole golden set the router sends fewer
    answerable = [i for i in load_items() if i.answerable]
    share = sum(route_question(i.question) == "agentic" for i in answerable) / len(answerable)
    per_path = {
        p: (
            statistics.mean(pair[i][p]["model_calls"] for i in ids),
            statistics.mean(pair[i][p]["tokens"] for i in ids),
        )
        for p in PATHS
    }
    calls = (1 - share) * per_path["fast"][0] + share * per_path["agentic"][0]
    tokens = (1 - share) * per_path["fast"][1] + share * per_path["agentic"][1]
    lines += [
        "",
        f"On all {len(answerable)} answerable golden questions the router sends {share:.0%} "
        f"agentic, so with these per-path costs it averages about {calls:.1f} model calls and "
        f"{tokens:.0f} tokens per question (always agentic: {per_path['agentic'][0]:.1f} and "
        f"{per_path['agentic'][1]:.0f}).",
    ]
    seconds = {p: [pair[i][p]["seconds"] for i in ids] for p in PATHS}
    lines += [
        "",
        f"Wall time per question (first run; cached reruns are faster): fast median "
        f"{statistics.median(seconds['fast']) if ids else 0:.1f} s, agentic median "
        f"{statistics.median(seconds['agentic']) if ids else 0:.1f} s.",
        f"Judge errors: {sum(1 for r in rows if r['judge_error'])} of {len(rows)} answers.",
        "",
        "Small sample, one judge model, golden answers quoted from the corpus: read the intervals,",
        "not the point estimates. The interaction cues of the router were widened after reading",
        "these questions (evals/reports/agents/router.md), so its choice here is optimistic.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    if "--report" in (argv if argv is not None else sys.argv[1:]):  # rewrite from saved rows
        write_report()
        return 0
    args = argv if argv is not None else sys.argv[1:]
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None  # development
    return run_all(limit)


if __name__ == "__main__":
    sys.exit(main())
