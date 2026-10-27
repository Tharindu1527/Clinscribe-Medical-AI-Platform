"""Answer evaluation: cited answers from stored rankings, judged per sentence (Phase 2 task 10).

  uv run python -m evals.rag.answer_eval --system dense              generate + judge (resumable)
  uv run python -m evals.rag.answer_eval --compare dense hybrid_colbert_ctx
  uv run python -m evals.rag.answer_eval --system hybrid_colbert_ctx --name hybrid_colbert_ctx_v2
      --prompt prompts/experiments/answer_cited_v2.yaml            a prompt trial, own row file

Questions: a seeded, stratified 60-question subset of the golden set (per area 10 answerable +
2 unanswerable). Context: the top 5 chunks of the system's stored ranking (evals/reports/rag/runs),
raw chunk text, so every system feeds the same generator (prompts/answer_cited.yaml) and the same
judge (prompts/judge_citations.yaml) — only retrieval differs.

Metrics per answer:
- citation precision: share of (sentence, cited chunk) links the judge rates "supports";
- faithfulness: share of sentences supported by at least one retrieved chunk;
- correctness: does the answer convey the golden quote (yes 1, partial 0.5, no 0; abstain 0);
- abstention: correct on unanswerable questions, false on answerable ones.
Every LLM response is cached (data/llm_cache, git-ignored), so reruns cost no quota. Free-tier
rate limits are waited out; when the wait means the daily budget is gone, the run stops cleanly and
resumes from the saved rows next time.
"""

import argparse
import json
import random
import re
import sys
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx
import yaml

from evals.golden.candidates import AREAS
from evals.golden.golden import GoldenItem, load_items
from evals.rag.metrics import paired_bootstrap
from llmops.gateway.client import ChatMessage, Completion, GatewayClient, ReplayCache, alias_for
from privacy.deid.types import issue
from retrieval.generate import AnswerGenerator, CitedAnswer, load_spec, source_block

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "evals" / "reports" / "rag"
RUNS = REPORTS / "runs"
OUT = REPORTS / "answers"
CACHE = ROOT / "data" / "llm_cache"
JUDGE_FILE = ROOT / "prompts" / "judge_citations.yaml"
TOP_K = 5
SEED = 11
PER_AREA = {"answerable": 10, "unanswerable": 2}
MAX_WAIT_S = 900  # a longer rate-limit wait means the daily budget is spent: stop and resume later
RATINGS = ("supports", "partial", "no")


class BudgetExhaustedError(RuntimeError):
    """The provider asked for a wait longer than MAX_WAIT_S (daily free-tier budget)."""


def wait_seconds(response: httpx.Response) -> float:
    """Seconds a 429 asks us to wait: Retry-After header, else 'try again in 1m2.5s' in the body."""
    header = response.headers.get("retry-after")
    if header and header.replace(".", "", 1).isdigit():
        return float(header)
    match = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", response.text)
    if match and any(match.groups()):
        h, m, s = (float(g) if g else 0.0 for g in match.groups())
        return h * 3600 + m * 60 + s
    return 30.0


class PatientClient:
    """Gateway client that waits out short rate limits and retries server errors."""

    def __init__(self, client: GatewayClient, *, fallbacks: bool = True) -> None:
        self._client = client
        self._fallbacks = fallbacks  # False: the named model or a wait, never another model

    def complete(self, model: str, messages: Sequence[ChatMessage], **kwargs: Any) -> Completion:
        if not self._fallbacks:
            kwargs["fallbacks"] = False
        for attempt in range(8):
            try:
                return self._client.complete(model, messages, **kwargs)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status == 429:
                    wait = wait_seconds(exc.response)
                    if wait > MAX_WAIT_S:
                        raise BudgetExhaustedError(
                            f"{model}: rate limit asks for {wait:.0f} s"
                        ) from None
                    print(f"  rate limited ({model}); waiting {wait:.0f} s", file=sys.stderr)
                    time.sleep(wait + 1)
                elif status >= 500 and attempt < 7:
                    time.sleep(10 * (attempt + 1))
                else:
                    raise
            except httpx.TransportError:
                if attempt == 7:
                    raise
                time.sleep(10 * (attempt + 1))
        raise BudgetExhaustedError(f"{model}: still rate limited after 8 attempts")


def stratified_subset(items: Sequence[GoldenItem], seed: int = SEED) -> list[GoldenItem]:
    rng = random.Random(seed)
    picked: list[GoldenItem] = []
    for area in AREAS:
        for kind, answerable in (("answerable", True), ("unanswerable", False)):
            group = sorted(
                (i for i in items if i.area == area and i.answerable == answerable),
                key=lambda i: i.id,
            )
            picked += rng.sample(group, min(PER_AREA[kind], len(group)))
    return sorted(picked, key=lambda i: i.id)


def judge_messages(
    spec: Mapping[str, Any],
    item: GoldenItem,
    chunks: Sequence[Mapping[str, str]],
    answer: CitedAnswer,
) -> list[ChatMessage]:
    sources, labels = source_block(chunks)
    label_of = {cid: label for label, cid in labels.items()}
    sentences = "\n".join(
        f"{n}. {s.text} (cites {', '.join(label_of[c] for c in s.chunk_ids)})"
        for n, s in enumerate(answer.sentences, start=1)
    )
    user = spec["user"].format(
        question=item.question,
        reference=f'"{item.answer}"'
        if item.answer
        else "none: the sources are not expected to answer",
        sources=sources,
        sentences=sentences,
    )
    return [
        ChatMessage("system", issue(spec["system"], "prompt")),
        ChatMessage("user", issue(user, "synthetic-golden-set+public-corpus+model-output")),
    ]


def parse_judgment(text: str, answer: CitedAnswer, labels: Mapping[str, str]) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    data = json.loads(text[start : end + 1]) if start >= 0 and end > start else None
    if not isinstance(data, dict) or not isinstance(data.get("sentences"), list):
        raise ValueError("judge reply has no sentences list")
    if len(data["sentences"]) != len(answer.sentences):
        raise ValueError(
            f"judge rated {len(data['sentences'])} of {len(answer.sentences)} sentences"
        )
    if data.get("matches_reference") not in ("yes", "partial", "no", "n/a"):
        raise ValueError("matches_reference must be yes, partial, no or n/a")
    label_of = {cid: label for label, cid in labels.items()}
    for sentence, rated in zip(answer.sentences, data["sentences"], strict=True):
        cited = rated.get("cited") or {}
        for chunk_id in sentence.chunk_ids:
            if cited.get(label_of[chunk_id]) not in RATINGS:
                raise ValueError(f"no rating for cited source {label_of[chunk_id]}")
        rated["supported_by"] = [s for s in rated.get("supported_by") or [] if s in labels]
    return data


def metrics(
    item: GoldenItem, answer: CitedAnswer, judgment: dict[str, Any] | None
) -> dict[str, Any]:
    out: dict[str, Any] = {"abstained": answer.abstained, "answerable": item.answerable}
    if item.answerable:
        out["false_abstain"] = answer.abstained
        if answer.abstained:
            out["correctness"] = 0.0
    else:
        out["correct_abstain"] = answer.abstained
    if answer.abstained or judgment is None:
        return out
    ratings = [r for s in judgment["sentences"] for r in (s.get("cited") or {}).values()]
    out["citation_precision"] = sum(r == "supports" for r in ratings) / len(ratings)
    out["faithfulness"] = sum(bool(s["supported_by"]) for s in judgment["sentences"]) / len(
        judgment["sentences"]
    )
    if item.answerable:
        out["correctness"] = {"yes": 1.0, "partial": 0.5}.get(judgment["matches_reference"], 0.0)
    return out


def run(
    system: str,
    items: Sequence[GoldenItem],
    client: PatientClient,
    prompt: Path | None = None,
    name: str | None = None,
) -> Path:
    """Answer and judge with one system's rankings; rows go to answers/<name>.jsonl (the system's
    name unless a prompt trial names its own file)."""
    spec = load_spec(prompt) if prompt else load_spec()
    judge_spec = yaml.safe_load(JUDGE_FILE.read_text(encoding="utf-8"))
    generator = AnswerGenerator(client, alias_for(spec.task), spec)
    judge_model = alias_for(judge_spec["task"])
    rankings = json.loads((RUNS / f"{system}.json").read_text(encoding="utf-8"))["results"]
    corpus = {
        (c := json.loads(line))["id"]: c
        for line in (ROOT / "data" / "corpus" / "chunks.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name or system}.jsonl"
    done = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            done[row["id"]] = row
    versions = {
        "answer": f"{spec.id}@v{spec.version}",
        "judge": f"{judge_spec['id']}@v{judge_spec['version']}",
    }
    with path.open("a", encoding="utf-8", newline="\n") as out:
        for n, item in enumerate(items, start=1):
            chunk_ids = rankings[item.id]["ranked"][:TOP_K]
            if (
                item.id in done
                and done[item.id]["chunk_ids"] == chunk_ids
                and done[item.id]["versions"] == versions
            ):
                continue
            chunks = [corpus[c] for c in chunk_ids]
            answer = generator.answer(issue(item.question, "synthetic-golden-set"), chunks)
            judgment, judge_error = None, None
            if not answer.abstained:
                _, labels = source_block(chunks)
                messages = judge_messages(judge_spec, item, chunks, answer)
                for _ in range(2):
                    reply = client.complete(
                        judge_model,
                        messages,
                        temperature=0.0,
                        max_tokens=judge_spec["max_tokens"],
                        response_format={"type": "json_object"},
                    )
                    try:
                        judgment = parse_judgment(reply.text, answer, labels)
                        break
                    except (ValueError, json.JSONDecodeError) as exc:
                        judge_error = str(exc)
                        messages = [
                            *messages,
                            ChatMessage("assistant", issue(reply.text, "model-output")),
                            ChatMessage(
                                "user",
                                issue(
                                    f"Invalid reply: {judge_error}. "
                                    "Reply again with valid JSON only.",
                                    "prompt",
                                ),
                            ),
                        ]
            row = {
                "id": item.id,
                "area": item.area,
                "qtype": item.qtype,
                "chunk_ids": chunk_ids,
                "versions": versions,
                "answer": answer.model_dump(),
                "judgment": judgment,
                "judge_error": None if judgment else judge_error,
                "metrics": metrics(item, answer, judgment),
            }
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            print(f"{system} {n}/{len(items)} {item.id}: {row['metrics']}", file=sys.stderr)
    return path


def load_rows(system: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for line in (OUT / f"{system}.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        rows[row["id"]] = row  # the last row for a question wins (a rerun after a prompt change)
    return rows


def summary(rows: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    def mean(key: str, answerable: bool | None = None) -> float | None:
        values = [
            r["metrics"][key]
            for r in rows.values()
            if key in r["metrics"]
            and (answerable is None or r["metrics"]["answerable"] == answerable)
        ]
        return round(sum(values) / len(values), 3) if values else None

    answerable = [r for r in rows.values() if r["metrics"]["answerable"]]
    return {
        "questions": len(rows),
        "answered": sum(not r["metrics"]["abstained"] for r in rows.values()),
        "faithfulness": mean("faithfulness"),
        "citation_precision": mean("citation_precision"),
        "correctness": mean("correctness"),
        "false_abstain_rate": mean("false_abstain"),
        "correct_abstain_rate": mean("correct_abstain"),
        "judge_errors": sum(1 for r in rows.values() if r.get("judge_error")),
        "answer_errors": sum(1 for r in rows.values() if r["answer"].get("error")),
        "generator_models": dict(Counter(r["answer"]["model"] for r in answerable)),
    }


def compare(baseline: str, candidate: str) -> Path:
    rows = {s: load_rows(s) for s in (baseline, candidate)}
    ids = sorted(set(rows[baseline]) & set(rows[candidate]))
    lines = [
        f"# Answers: `{candidate}` vs `{baseline}`",
        "",
        f"{len(ids)} questions (stratified subset of the golden set); generator and judge per "
        "prompts/answer_cited.yaml and prompts/judge_citations.yaml; 95% paired bootstrap.",
        "",
        "| metric | baseline | candidate | difference | 95% CI | n pairs | better? |",
        "|---|---|---|---|---|---|---|",
    ]
    for key in ("faithfulness", "citation_precision", "correctness"):
        pairs = [
            (rows[baseline][i]["metrics"][key], rows[candidate][i]["metrics"][key])
            for i in ids
            if key in rows[baseline][i]["metrics"] and key in rows[candidate][i]["metrics"]
        ]
        if not pairs:
            continue
        a, b = [p[0] for p in pairs], [p[1] for p in pairs]
        diff, low, high = paired_bootstrap(a, b)
        verdict = "yes" if low > 0 else "no" if high < 0 else "not shown"
        lines.append(
            f"| {key} | {sum(a) / len(a):.3f} | {sum(b) / len(b):.3f} | {diff:+.3f} | "
            f"[{low:+.3f}, {high:+.3f}] | {len(pairs)} | {verdict} |"
        )
    lines += [
        "",
        "| system | answered | false abstain (answerable) | correct abstain (unanswerable) "
        "| judge errors |",
        "|---|---|---|---|---|",
    ]
    for system in (baseline, candidate):
        s = summary({i: rows[system][i] for i in ids})
        lines.append(
            f"| {system} | {s['answered']}/{s['questions']} | {s['false_abstain_rate']} | "
            f"{s['correct_abstain_rate']} | {s['judge_errors']} |"
        )
    path = REPORTS / f"answers_{candidate}_vs_{baseline}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


def main(argv: list[str] | None = None) -> int:
    from config.settings import Settings

    parser = argparse.ArgumentParser(description="Cited-answer evaluation")
    parser.add_argument("--system", action="append", help="retrieval system(s) to answer with")
    parser.add_argument("--compare", nargs=2, metavar=("BASELINE", "CANDIDATE"))
    parser.add_argument("--limit", type=int, help="first N questions of the subset (smoke run)")
    parser.add_argument(
        "--prompt", type=Path, help="answer prompt to try instead of the production one"
    )
    parser.add_argument("--name", help="row file name for a prompt trial (default: the system)")
    args = parser.parse_args(argv)
    if args.name and len(args.system or []) != 1:
        parser.error("--name goes with exactly one --system")
    if args.compare:
        print(compare(*args.compare).read_text(encoding="utf-8"))
        return 0
    settings = Settings()
    gateway = GatewayClient(
        settings.gateway_url,
        settings.litellm_app_key,
        cache=ReplayCache(CACHE, "record"),
        timeout=180.0,
        trace=False,  # bulk eval calls stay out of Langfuse (no-log)
    )
    items = (
        stratified_subset(load_items())[: args.limit]
        if args.limit
        else stratified_subset(load_items())
    )
    try:
        for system in args.system or ["dense"]:
            # no fallbacks: a gateway failover would answer some questions with another model
            path = run(
                system, items, PatientClient(gateway, fallbacks=False), args.prompt, args.name
            )
            name = args.name or system
            print(json.dumps({name: summary(load_rows(name))}, indent=2))
            print(f"rows: {path}")
    except BudgetExhaustedError as exc:
        print(f"stopped: {exc}. Saved rows are kept; rerun the same command later to resume.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
