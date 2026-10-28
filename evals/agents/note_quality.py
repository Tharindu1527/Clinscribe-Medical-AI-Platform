"""Note quality against the clinician's reference note (SPEC section 11, "Notes": ACI-Bench, a
rubric-based LLM judge; the doctor spot check is not done).

The drafts come from the note evaluation's set-up (evals/agents/note_eval.py): the same seeded
ACI-Bench dialogues, de-identified turn by turn by the running de-ID service, then the graph. The
model cache replays a draft only when the de-identified transcript is unchanged, so a de-ID change
(the tagger, ADR-0014) means fresh drafts. The reference note goes through the de-ID service
with the same encounter id, so placeholders match. The judge, a larger model than the note
writer, answers two questions in two calls (each must fit Groq's free 8k tokens per minute):
- coverage (prompts/judge_note.yaml): the reference's important facts, most important first, and
  whether the draft conveys each (fact recall; "critical" facts separately);
- support (prompts/judge_note_support.yaml): every draft statement against the transcript turns
  it cites (unsupported = something the turns do not say), and whether its section fits.

Controls, coverage only: the reference note itself as the draft (recall should be near 1), and the
draft without its assessment and plan statements (critical recall should fall).

  uv run python -m evals.agents.note_quality [--n 8]   (needs `just up`: de-ID + gateway)
Writes evals/reports/agents/note_quality.md. Judge responses are cached in data/llm_cache.

`--alias clinscribe-eval-gemini-2.5-flash` pins the note writer to one model, with no fallbacks
(ADR-0030), and writes `note_quality_<alias>.md` with every note-writer reply: finish reason
("length" is a cut-off), thinking tokens and latency, and the ADR's adoption rule checked.
"""

import argparse
import csv
import hashlib
import json
import random
import re
import statistics
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import yaml
from langgraph.checkpoint.memory import InMemorySaver

from agents.graph import Agents
from config.settings import Settings
from evals.agents.note_eval import DATA, SEED, SHA256, NoTools, turns
from evals.rag.answer_eval import BudgetExhaustedError, PatientClient
from llmops.gateway.client import (
    ChatMessage,
    Completion,
    GatewayClient,
    ReplayCache,
    alias_for,
)
from privacy.deid.client import DeidClient
from privacy.deid.types import issue

ROOT = Path(__file__).resolve().parents[2]
COVERAGE = ROOT / "prompts" / "judge_note.yaml"
SUPPORT_PROMPT = ROOT / "prompts" / "judge_note_support.yaml"
REPORT = ROOT / "evals" / "reports" / "agents" / "note_quality.md"
COVERED = {"yes": 1.0, "partial": 0.5, "no": 0.0}
SUPPORT = {"supported": 1.0, "partial": 0.5, "unsupported": 0.0}
HEADING = re.compile(r"^[A-Z][A-Z &/-]{3,}$")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
# Groq's free tier counts prompt + max_tokens against the judge model's 8,000 tokens per minute and
# refuses a larger request outright ("Request too large"), so each call asks for what fits
TPM_LIMIT = 8000
CHARS_PER_TOKEN = 3.2  # a cautious estimate for clinical English
MIN_REPLY = 1500
# ADR-0030's rule, written before the pinned run: the committed pool run had recall 0.85, critical
# recall 0.92 and 3 of 171 statements unsupported; margin 0.05, at most 3% unsupported
RULE = {"recall": 0.80, "critical_recall": 0.87, "unsupported_share": 0.03}


class Recording:
    """Passes calls through and keeps the note writer's replies (model `alias`)."""

    def __init__(self, client: PatientClient, alias: str) -> None:
        self._client, self._alias = client, alias
        self.calls: list[Completion] = []

    def complete(self, model: str, messages: Sequence[ChatMessage], **kwargs: Any) -> Completion:
        reply = self._client.complete(model, messages, **kwargs)
        if model == self._alias:
            self.calls.append(reply)
        return reply


def reference_as_draft(note: str) -> list[dict[str, Any]]:
    """The reference note as sentence statements under its headings (the positive control)."""
    out: list[dict[str, Any]] = []
    section = "reference"
    for line in note.splitlines():
        line = line.strip()
        if not line:
            continue
        if HEADING.match(line):
            section = line.lower()
            continue
        out += [
            {"section": section, "text": s, "transcript_turns": []}
            for s in SENTENCE_END.split(line)
        ]
    return out


def coverage_block(statements: list[dict[str, Any]]) -> str:
    return "\n".join(f"{n}. [{s['section']}] {s['text']}" for n, s in enumerate(statements, 1))


def support_blocks(statements: list[dict[str, Any]], transcript: list[str]) -> tuple[str, str]:
    """The cited turns once each, and the statements with their turn numbers."""
    cited = sorted(
        {t for s in statements for t in s.get("transcript_turns", []) if t < len(transcript)}
    )
    turn_lines = "\n".join(f"[{t}] {transcript[t]}" for t in cited)
    lines = []
    for n, s in enumerate(statements, 1):
        numbers = ", ".join(map(str, s.get("transcript_turns", []))) or "none"
        lines.append(f"{n}. [{s['section']}] {s['text']} (turns: {numbers})")
    return turn_lines, "\n".join(lines)


def parse_coverage(text: str, max_facts: int) -> list[dict[str, Any]]:
    data = _json(text)
    facts = data.get("facts")
    if not isinstance(facts, list) or not facts:
        raise ValueError("facts must be a non-empty list")
    for fact in facts:
        if fact.get("covered") not in COVERED or not isinstance(fact.get("critical"), bool):
            raise ValueError("every fact needs covered (yes/partial/no) and critical (true/false)")
    return facts[:max_facts]  # listed most important first: a longer list keeps its top


def parse_support(text: str, n_statements: int) -> list[dict[str, Any]]:
    rated = _json(text).get("statements")
    if not isinstance(rated, list) or sorted(r.get("n") for r in rated) != list(
        range(1, n_statements + 1)
    ):
        raise ValueError(f"rate each of the {n_statements} statements exactly once")
    if any(r.get("support") not in (*SUPPORT, "n/a") for r in rated):
        raise ValueError("support must be supported, partial, unsupported or n/a")
    return rated


def _json(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    data = json.loads(text[start : end + 1]) if start >= 0 and end > start else None
    if not isinstance(data, dict):
        raise ValueError("the reply has no JSON object")
    return data


def ask(client: PatientClient, spec: dict[str, Any], user: str, parse: Callable[[str], Any]) -> Any:
    """One judge call that fits the per-minute limit, retried once with the validation error."""
    messages = [
        ChatMessage("system", issue(spec["system"], "prompt")),
        ChatMessage("user", issue(user, "aci-bench-deidentified+model-output")),
    ]
    error = ""
    for _ in range(2):
        prompt_tokens = sum(len(m.content.text) for m in messages) / CHARS_PER_TOKEN
        max_tokens = int(min(spec["max_tokens"], TPM_LIMIT - prompt_tokens - 200))
        if max_tokens < MIN_REPLY:
            raise ValueError(f"the prompt (~{prompt_tokens:.0f} tokens) leaves no room to reply")
        reply = client.complete(
            alias_for(spec["task"]),
            messages,
            temperature=spec["temperature"],
            max_tokens=max_tokens,
            reasoning_effort=spec.get("reasoning_effort"),
        )
        try:
            return parse(reply.text)
        except (ValueError, json.JSONDecodeError) as exc:
            error = str(exc)
            messages = [
                *messages,
                ChatMessage("assistant", issue(reply.text, "model-output")),
                ChatMessage("user", issue(f"Invalid reply: {error}. Reply again.", "prompt")),
            ]
    raise ValueError(f"judge reply invalid twice: {error}")


def recall(
    client: PatientClient, spec: dict[str, Any], reference: str, statements: list[dict[str, Any]]
) -> dict[str, Any]:
    user = spec["user"].format(
        reference=reference, statements=coverage_block(statements), max_facts=spec["max_facts"]
    )
    facts = ask(client, spec, user, lambda text: parse_coverage(text, spec["max_facts"]))
    critical = [f for f in facts if f["critical"]]
    return {
        "facts": len(facts),
        "recall": statistics.mean(COVERED[f["covered"]] for f in facts),
        "critical_recall": statistics.mean(COVERED[f["covered"]] for f in critical)
        if critical
        else None,
        "missed_critical": [str(f.get("fact", "")) for f in critical if f["covered"] == "no"],
    }


def support(
    client: PatientClient,
    spec: dict[str, Any],
    statements: list[dict[str, Any]],
    transcript: list[str],
) -> dict[str, Any]:
    turn_lines, statement_lines = support_blocks(statements, transcript)
    user = spec["user"].format(turns=turn_lines, statements=statement_lines)
    rated = ask(client, spec, user, lambda text: parse_support(text, len(statements)))
    scored = [r for r in rated if r["support"] in SUPPORT]
    return {
        "support": statistics.mean(SUPPORT[r["support"]] for r in scored) if scored else None,
        "unsupported": sum(r["support"] == "unsupported" for r in scored),
        "section_ok": statistics.mean(bool(r.get("section_ok")) for r in rated),
        "unsupported_text": [
            str(statements[r["n"] - 1]["text"]) for r in scored if r["support"] == "unsupported"
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=8)
    parser.add_argument("--alias", help="pin the note writer to this gateway alias, no fallbacks")
    args = parser.parse_args(argv)
    if hashlib.sha256(DATA.read_bytes()).hexdigest() != SHA256:
        raise SystemExit(f"{DATA} missing or changed")
    rows = random.Random(SEED).sample(list(csv.DictReader(DATA.open(encoding="utf-8"))), args.n)
    settings = Settings()
    deid = DeidClient(settings.deid_url)
    gateway = GatewayClient(
        settings.gateway_url,
        settings.litellm_app_key,
        cache=ReplayCache(ROOT / "data" / "llm_cache", "record"),
        timeout=300,
        trace=False,
    )
    client = PatientClient(gateway, fallbacks=not args.alias)
    writer = args.alias or alias_for("note_writer")
    recording = Recording(client, writer)
    graph = Agents(
        recording,
        NoTools(),
        alias=lambda task: writer if task == "note_writer" else alias_for(task),
    ).build(InMemorySaver())
    cover = yaml.safe_load(COVERAGE.read_text(encoding="utf-8"))
    back = yaml.safe_load(SUPPORT_PROMPT.read_text(encoding="utf-8"))
    results: list[dict[str, Any]] = []
    try:
        for row in rows:
            encounter = f"aci-{row['encounter_id']}"
            before = len(recording.calls)
            transcript = [
                f"{speaker.upper()}: {deid.deidentify(text, encounter).text.text}"
                for speaker, text in turns(row["dialogue"])
            ]
            out = graph.invoke(
                {"mode": "scribe", "encounter_id": encounter, "patient_id": "eval",
                 "transcript": transcript},
                {"configurable": {"thread_id": encounter}},
            )  # fmt: skip
            calls = recording.calls[before:]
            if not out.get("__interrupt__"):
                results.append({"id": encounter, "draft": False, "calls": calls})
                continue
            draft = out["__interrupt__"][0].value["draft"]["statements"]
            reference = deid.deidentify(row["note"], encounter).text.text
            no_plan = [s for s in draft if s["section"] not in ("assessment", "plan")]
            try:
                result = {
                    "id": encounter,
                    "draft": True,
                    "calls": calls,
                    "statements": len(draft),
                    "draft_scores": {
                        **recall(client, cover, reference, draft),
                        **support(client, back, draft, transcript),
                    },
                    "reference_control": recall(
                        client, cover, reference, reference_as_draft(reference)
                    ),
                    "no_plan_control": recall(client, cover, reference, no_plan),
                }
            except ValueError as exc:  # the judge failed on this note: report it, go on
                results.append(
                    {"id": encounter, "draft": True, "judge_error": str(exc), "calls": calls}
                )
                print(encounter, "judge error:", exc, file=sys.stderr)
                continue
            results.append(result)
            print(encounter, json.dumps(result["draft_scores"]), file=sys.stderr)
    except BudgetExhaustedError as exc:
        print(f"stopped: {exc}. Rerun later: judged notes are cached.", file=sys.stderr)
        return 2
    path = REPORT.with_name(f"note_quality_{args.alias}.md") if args.alias else REPORT
    write_report(results, cover, back, path, pinned=args.alias)
    print(path.read_text(encoding="utf-8"))
    return 0


def _mean(values: list[Any]) -> str:
    present = [v for v in values if v is not None]
    return f"{statistics.mean(present):.2f}" if present else "-"


def write_report(
    results: list[dict[str, Any]],
    cover: dict[str, Any],
    back: dict[str, Any],
    path: Path = REPORT,
    pinned: str | None = None,
) -> None:
    judged = [r for r in results if r["draft"] and "judge_error" not in r]
    d = [r["draft_scores"] for r in judged]
    ref = [r["reference_control"] for r in judged]
    nop = [r["no_plan_control"] for r in judged]
    lines = [
        "# Note quality vs the reference note (ACI-Bench, rubric judge)"
        + (f": note writer on `{pinned}`" if pinned else ""),
        "",
        "Generated by `evals/agents/note_quality.py`: drafts for the note evaluation's "
        f"{len(results)} dialogues, written with the current de-ID and note writer"
        + (f" pinned to `{pinned}` (no fallbacks)" if pinned else "")
        + ", judged by",
        f"`{cover['id']}@v{cover['version']}` and `{back['id']}@v{back['version']}` "
        f"({alias_for(cover['task'])}) against the clinician's reference note, all de-identified.",
        "Recall: share of the reference's important facts the draft conveys (yes 1, partial 0.5);",
        "critical: medications and doses, allergies, abnormal results, the plan. Support: draft",
        "statements backed by the transcript turns they cite. One judge model, no clinician check:",
        "read as indicative.",
        "",
        "| | Fact recall | Critical recall | Statement support | Unsupported statements | "
        "Section fits |",
        "|---|---|---|---|---|---|",
        f"| drafts (mean of {len(judged)}) | {_mean([s['recall'] for s in d])} | "
        f"{_mean([s['critical_recall'] for s in d])} | {_mean([s['support'] for s in d])} | "
        f"{sum(int(s['unsupported'] or 0) for s in d)} of {sum(r['statements'] for r in judged)} | "
        f"{_mean([s['section_ok'] for s in d])} |",
        f"| control: the reference as the draft | {_mean([s['recall'] for s in ref])} | "
        f"{_mean([s['critical_recall'] for s in ref])} | - | - | - |",
        f"| control: draft without assessment and plan | {_mean([s['recall'] for s in nop])} | "
        f"{_mean([s['critical_recall'] for s in nop])} | - | - | - |",
        "",
        "| dialogue | statements | facts | recall | critical recall | support | unsupported |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        if not r["draft"]:
            lines.append(f"| {r['id']} | no draft | - | - | - | - | - |")
        elif "judge_error" in r:
            lines.append(
                f"| {r['id']} | judge failed: {r['judge_error'][:60]} | - | - | - | - | - |"
            )
        else:
            s = r["draft_scores"]
            lines.append(
                f"| {r['id']} | {r['statements']} | {s['facts']} | {s['recall']:.2f} | "
                f"{_mean([s['critical_recall']])} | {_mean([s['support']])} | {s['unsupported']} |"
            )
    lines += [
        "",
        "## What the judge found missing or unsupported",
        "",
        "Critical reference facts the draft does not convey at all (partly conveyed ones are",
        "not listed), and draft statements their cited turns do not support. De-identified",
        "text, as the judge saw it.",
        "",
    ]
    for r in judged:
        s = r["draft_scores"]
        if not s["missed_critical"] and not s["unsupported_text"]:
            continue
        lines.append(f"- **{r['id']}**")
        lines += [f"  - missed (critical): {fact}" for fact in s["missed_critical"]]
        lines += [f"  - unsupported: {text}" for text in s["unsupported_text"]]
    if pinned:
        lines += writer_replies(results, d, judged)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def writer_replies(
    results: list[dict[str, Any]], d: list[dict[str, Any]], judged: list[dict[str, Any]]
) -> list[str]:
    """The pinned run's note-writer replies, and ADR-0030's rule checked."""
    calls = [c for r in results for c in r["calls"]]
    cut = [c for c in calls if c.finish_reason == "length"]
    lines = [
        "",
        "## Note-writer replies",
        "",
        "Every reply of the pinned model, first attempts and retries. Thinking tokens count",
        'inside the output tokens; "length" means the reply stopped at the output limit.',
        "",
        "| dialogue | replies | finish reasons | output tokens | thinking tokens | latency (s) |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        cs = r["calls"]
        lines.append(
            f"| {r['id']} | {len(cs)} | {', '.join(str(c.finish_reason) for c in cs)} | "
            f"{', '.join(str(c.output_tokens) for c in cs)} | "
            f"{', '.join(str(c.reasoning_tokens) for c in cs)} | "
            f"{', '.join(f'{c.latency_ms / 1000:.1f}' for c in cs)} |"
        )
    latency = sorted(c.latency_ms for c in calls)
    if latency:
        p95 = latency[min(len(latency) - 1, round(0.95 * (len(latency) - 1)))]
        lines += [
            "",
            f"Replies cut off: {len(cut)} of {len(calls)}. Thinking tokens: median "
            f"{statistics.median(c.reasoning_tokens for c in calls):.0f}, most "
            f"{max(c.reasoning_tokens for c in calls)}. Latency per reply: p50 "
            f"{statistics.median(latency) / 1000:.1f} s, p95 {p95 / 1000:.1f} s.",
        ]
    statements = sum(r["statements"] for r in judged)
    unsupported = sum(int(s["unsupported"] or 0) for s in d)
    critical = [s["critical_recall"] for s in d if s["critical_recall"] is not None]
    checks = [
        (
            "every dialogue drafted and judged, no reply cut off",
            all(r["draft"] for r in results) and not cut and len(judged) == len(results),
        ),
        (
            f"fact recall >= {RULE['recall']}",
            bool(d) and statistics.mean(s["recall"] for s in d) >= RULE["recall"],
        ),
        (
            f"critical recall >= {RULE['critical_recall']}",
            bool(critical) and statistics.mean(critical) >= RULE["critical_recall"],
        ),
        (
            f"unsupported <= {RULE['unsupported_share']:.0%} of statements",
            bool(statements) and unsupported / statements <= RULE["unsupported_share"],
        ),
    ]
    lines += ["", "## ADR-0030 rule (written before this run)", ""]
    lines += [f"- {'PASS' if ok else 'FAIL'}: {name}" for name, ok in checks]
    verdict = "adopt" if all(ok for _, ok in checks) else "do not adopt"
    lines.append(f"- **{verdict}** the thinking budget on the pool deployment")
    return lines


if __name__ == "__main__":
    sys.exit(main())
