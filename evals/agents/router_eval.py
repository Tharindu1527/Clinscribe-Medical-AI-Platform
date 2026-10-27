"""Ask-mode router on the golden set (Phase 3 task 5, ablation step 7). No model calls.

Which golden questions the router sends to the agentic loop, against the question type. Missing an
interaction question is the costly error (drug facts from the graph are added only on the agentic
path); an unnecessary agentic route costs one grading call (and at most one rewrite).

  uv run python -m evals.agents.router_eval
"""

import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from agents.graph import COMPARISON, route_question
from evals.golden.golden import load_items

REPORT = Path(__file__).resolve().parents[2] / "evals" / "reports" / "agents" / "router.md"


def main() -> int:
    items = load_items()
    rules: dict[str, Callable[[str], bool]] = {
        "comparison wording only": lambda q: bool(COMPARISON.search(q)),
        "chosen: + interaction cues, several questions, long questions": lambda q: (
            route_question(q) == "agentic"
        ),
    }
    lines = [
        "# Ask router (ablation step 7)",
        "",
        f"{len(items)} golden questions. The interaction cues come from the Phase 2 graph router,",
        "whose rules were widened after reading these questions, so recall here is optimistic.",
        "",
        "| rule | interaction questions routed agentic | other questions routed agentic |",
        "|---|---|---|",
    ]
    for name, rule in rules.items():
        c = Counter((i.qtype == "interaction", rule(i.question)) for i in items)
        hit, miss, extra, rest = (
            c[(True, True)],
            c[(True, False)],
            c[(False, True)],
            c[(False, False)],
        )
        lines.append(f"| {name} | {hit}/{hit + miss} | {extra}/{extra + rest} |")
    by_type = Counter((i.qtype, route_question(i.question)) for i in items)
    lines += ["", "| question type | fast | agentic |", "|---|---|---|"]
    for qtype in sorted({i.qtype for i in items}):
        lines.append(f"| {qtype} | {by_type[(qtype, 'fast')]} | {by_type[(qtype, 'agentic')]} |")
    lines += [
        "",
        "Cost per question: fast = 1 model call (answer); agentic = 2-3 (grading, at most one",
        "rewrite, answer) plus one druggraph-mcp call when two or more drug names are present.",
        "Answer quality fast vs agentic was not measured on the free-tier budget; the agentic",
        "path's measured value so far is the graph-only check (task 10: 10/10 vs 4/10 answered).",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(REPORT.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
