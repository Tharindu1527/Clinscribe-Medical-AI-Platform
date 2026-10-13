"""Note-writer evaluation on ACI-Bench dialogues (Phase 3 task 6; SPEC section 11).

Seeded sample of the ACI-Bench validation dialogues (CC BY 4.0, data/LICENSES.md). Every turn goes
through the de-ID service first (the dialogues contain names), then the real graph runs the scribe
path with the real model up to the doctor-review interrupt. Measured: drafts produced, schema
validity on the first attempt (no retry needed), statements and sections, statements removed by
the guardrails (by rule), unsupported assessment/plan statements, latency. Model responses are
cached (data/llm_cache), so a rerun makes no calls.

  uv run python -m evals.agents.note_eval [--n 8]     (needs `just up`: de-ID + gateway)
"""

import argparse
import csv
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from agents.graph import Agents
from agents.prompts import load
from config.settings import Settings
from evals.rag.answer_eval import PatientClient
from evals.rag.metrics import percentile
from llmops.gateway.client import GatewayClient, ReplayCache
from privacy.deid.client import DeidClient

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "raw" / "aci-bench" / "valid.csv"
SHA256 = "6629e89e3fb409d2b3eceab60dc7b32fe1d3fb8d4e07795039284965522aa4d0"
REPORT = ROOT / "evals" / "reports" / "agents" / "note_writer.md"
SEED = 3


class NoTools:
    def search(self, request: Any) -> Any:
        raise AssertionError("the scribe path does not search")

    interactions = patient_context = write = search


def turns(dialogue: str) -> list[tuple[str, str]]:
    out = []
    for line in dialogue.splitlines():
        match = re.match(r"\[(doctor|patient|patient_guest|doctor_guest)\]\s*(.*)", line.strip())
        if match and match.group(2):
            speaker = "doctor" if match.group(1).startswith("doctor") else "patient"
            out.append((speaker, match.group(2)))
    return out


def main(argv: list[str] | None = None) -> int:
    import hashlib

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=8)
    args = parser.parse_args(argv)
    if hashlib.sha256(DATA.read_bytes()).hexdigest() != SHA256:
        raise SystemExit(f"{DATA} missing or changed (expected sha256 {SHA256[:12]}...)")
    rows = list(csv.DictReader(DATA.open(encoding="utf-8")))
    sample = random.Random(SEED).sample(rows, args.n)
    settings = Settings()
    deid = DeidClient(settings.deid_url)
    gateway = GatewayClient(
        settings.gateway_url,
        settings.litellm_app_key,
        cache=ReplayCache(ROOT / "data" / "llm_cache", "record"),
        timeout=300,
        trace=False,
    )
    graph = Agents(PatientClient(gateway), NoTools()).build(InMemorySaver())
    results = []
    for row in sample:
        encounter = f"aci-{row['encounter_id']}"
        transcript = [
            f"{speaker.upper()}: {deid.deidentify(text, encounter).text.text}"
            for speaker, text in turns(row["dialogue"])
        ]
        started = time.perf_counter()
        out = graph.invoke(
            {
                "mode": "scribe",
                "encounter_id": encounter,
                "patient_id": "eval",
                "transcript": transcript,
            },
            {"configurable": {"thread_id": encounter}},
        )
        seconds = time.perf_counter() - started
        state = graph.get_state({"configurable": {"thread_id": encounter}}).values
        pending = out.get("__interrupt__")
        statements = pending[0].value["draft"]["statements"] if pending else []
        removed = pending[0].value["removed"] if pending else state.get("violations", [])
        results.append(
            {
                "id": encounter,
                "turns": len(transcript),
                "draft": bool(pending),
                "attempts": state.get("attempts", 0),
                "statements": len(statements),
                "sections": Counter(s["section"] for s in statements),
                "unsupported": len(pending[0].value["unsupported"]) if pending else 0,
                "removed": [r.split(":")[0] for r in removed],
                "seconds": seconds,
            }
        )
        print(encounter, results[-1]["statements"], "statements, attempts", results[-1]["attempts"])
    write_report(results)
    print(REPORT.read_text(encoding="utf-8"))
    return 0


def write_report(results: list[dict[str, Any]]) -> None:
    n = len(results)
    drafts = sum(r["draft"] for r in results)
    first = sum(r["draft"] and r["attempts"] == 1 for r in results)
    statements = sum(r["statements"] for r in results)
    removed = Counter(rule for r in results for rule in r["removed"])
    sections: Counter[str] = Counter()
    for r in results:
        sections.update(r["sections"])
    seconds = [r["seconds"] for r in results if r["seconds"] > 1]  # cached reruns take ~0 s
    lines = [
        "# Note writer on ACI-Bench (Phase 3 task 6)",
        "",
        f"{n} validation dialogues (seed {SEED}, CC BY 4.0), de-identified turn by turn, then the",
        "scribe path of the graph with the real model up to the doctor-review interrupt (prompt",
        f"`{load('note_writer').ref}`, alias `clinscribe-default`).",
        "",
        f"- drafts produced: {drafts}/{n}",
        f"- schema-valid and guardrail-clean on the first attempt: {first}/{n} "
        f"({first / n:.0%}); the rest needed the one retry",
        f"- statements: {statements} ({statements / max(drafts, 1):.1f} per draft); by section: "
        + ", ".join(f"{k} {v}" for k, v in sections.most_common()),
        f"- assessment/plan statements without a guideline citation (highlighted for the doctor): "
        f"{sum(r['unsupported'] for r in results)}",
        "- problems after the retry (statements removed): "
        + (", ".join(f"{k} {v}" for k, v in removed.most_common()) or "none"),
        (
            f"- latency per draft (uncached runs): p50 {percentile(seconds, 0.5):.0f} s, "
            f"p95 {percentile(seconds, 0.95):.0f} s"
            if seconds
            else "- latency: all responses cached"
        ),
        "",
        "| dialogue | turns | draft | attempts | statements | unsupported | removed |",
        "|---|---|---|---|---|---|---|",
        *[
            f"| {r['id']} | {r['turns']} | {'yes' if r['draft'] else 'no'} | {r['attempts']} | "
            f"{r['statements']} | {r['unsupported']} | {len(r['removed'])} |"
            for r in results
        ],
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    sys.exit(main())
