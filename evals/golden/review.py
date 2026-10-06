"""Human review of a stratified 20% sample of the golden set (Phase 2 decision, 2026-10-06).

  uv run python -m evals.golden.review make     write evals/golden/review/review_v1.csv
  uv run python -m evals.golden.review summary  check a filled sheet and print the verdicts

The reviewer fills `verdict` (ok / fix / reject), `reviewer`, `reviewed_on` (YYYY-MM-DD) and, for
fix or reject, `notes` (and `corrected_question` if the wording is the problem). The filled sheet
is committed as the record of who reviewed what. The CSV is UTF-8 with a BOM so Excel shows
symbols (≥, µ, –) correctly.
"""

import argparse
import csv
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from evals.golden.golden import CORPUS_CHUNKS, GOLDEN, GoldenItem, load_items

REVIEW_DIR = Path(__file__).resolve().parent / "review"
SHEET = REVIEW_DIR / "review_v1.csv"
SAMPLE_SHARE = 0.20
SEED = 7
VERDICTS = ("ok", "fix", "reject")
COLUMNS = [
    "id", "area", "qtype", "answerable", "question", "answer_quote", "source_url", "source_passage",
    "verdict", "corrected_question", "notes", "reviewer", "reviewed_on",
]  # fmt: skip


def stratified_sample(items: list[GoldenItem], share: float = SAMPLE_SHARE) -> list[GoldenItem]:
    """At least `share` of every (area, answerable) group, rounded up, chosen with a fixed seed."""
    groups: dict[tuple[str, bool], list[GoldenItem]] = defaultdict(list)
    for item in items:
        groups[(item.area, item.answerable)].append(item)
    rng = random.Random(SEED)
    picked = []
    for key in sorted(groups):
        group = sorted(groups[key], key=lambda i: i.id)
        k = -(-len(group) * int(share * 100) // 100)  # ceil without float error
        picked += rng.sample(group, k)
    return sorted(picked, key=lambda i: i.id)


def make(items: list[GoldenItem], path: Path = SHEET) -> int:
    chunks = {
        (c := json.loads(line))["id"]: c
        for line in CORPUS_CHUNKS.read_text(encoding="utf-8").splitlines()
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    sample = stratified_sample(items)
    with path.open("w", encoding="utf-8-sig", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=COLUMNS)
        writer.writeheader()
        for item in sample:
            first = chunks[item.gold_chunk_ids[0]] if item.gold_chunk_ids else None
            writer.writerow(
                {
                    "id": item.id,
                    "area": item.area,
                    "qtype": item.qtype,
                    "answerable": "yes" if item.answerable else "no",
                    "question": item.question,
                    "answer_quote": item.answer or "",
                    "source_url": first["url"] if first else "",
                    "source_passage": (
                        first["text"]
                        if first
                        else "Should NOT be answerable from the corpus; none of these terms occur "
                        f"in it: {', '.join(item.absent_terms)}"
                    ),
                }
            )
    return len(sample)


def read_sheet(path: Path = SHEET) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sheet_problems(rows: list[dict[str, str]], golden_ids: set[str]) -> list[str]:
    problems = []
    for row in rows:
        rid = row.get("id", "?")
        if rid not in golden_ids:
            problems.append(f"{rid}: not in the golden set")
        verdict = (row.get("verdict") or "").strip().lower()
        if verdict not in VERDICTS:
            problems.append(f"{rid}: verdict must be one of {VERDICTS}, got '{verdict}'")
        if not (row.get("reviewer") or "").strip():
            problems.append(f"{rid}: reviewer is empty")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", (row.get("reviewed_on") or "").strip()):
            problems.append(f"{rid}: reviewed_on must be YYYY-MM-DD")
        if verdict in ("fix", "reject") and not (row.get("notes") or "").strip():
            problems.append(f"{rid}: '{verdict}' needs a note saying what is wrong")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Golden-set review sheet")
    parser.add_argument("action", choices=["make", "summary"])
    args = parser.parse_args(argv)
    items = load_items(GOLDEN)
    if args.action == "make":
        if SHEET.exists() and any((r.get("verdict") or "").strip() for r in read_sheet()):
            print(f"{SHEET} already has verdicts; not overwriting the review record.")
            return 1
        n = make(items)
        print(f"wrote {n} rows ({n / len(items):.0%} of {len(items)} items) to {SHEET}")
        return 0
    rows = read_sheet()
    problems = sheet_problems(rows, {i.id for i in items})
    verdicts = Counter((r.get("verdict") or "").strip().lower() for r in rows)
    print(f"rows {len(rows)} ({len(rows) / len(items):.0%} of the set); verdicts {dict(verdicts)}")
    print(f"reviewers: {sorted({(r.get('reviewer') or '').strip() for r in rows} - {''})}")
    for problem in problems:
        print("PROBLEM", problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
