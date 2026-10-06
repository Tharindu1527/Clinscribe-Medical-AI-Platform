"""Golden Q&A set: schema, validation and gold-chunk expansion (PROGRESS Phase 2 task 3).

Every answerable item quotes its answer verbatim from the corpus, so "the gold chunk contains the
answer" is checked by string matching, not by judgement. Gold chunk ids are all chunks containing
the quote (neighbouring chunks overlap by 40 words). Unanswerable items name terms that must
not appear anywhere in the corpus.

Usage:
  uv run python -m evals.golden.golden            validate and print coverage
  uv run python -m evals.golden.golden --expand   also rewrite gold_chunk_ids from the quotes
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from evals.golden.candidates import AREAS

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "evals" / "golden" / "golden_v1.jsonl"
CORPUS_CHUNKS = ROOT / "data" / "corpus" / "chunks.jsonl"
MIN_ITEMS = 200
MIN_UNANSWERABLE_SHARE = 0.10
MIN_PER_AREA = 35  # answerable items per clinical area
COPY_NGRAM = 6  # a question sharing 6+ consecutive words with its gold chunk copies the source

QType = Literal[
    "dose", "interaction", "contraindication", "recommendation", "adverse_effect", "fact"
]


class GoldenItem(BaseModel):
    id: str = Field(pattern=r"^g\d{4}$")
    question: str = Field(min_length=15)
    answerable: bool
    answer: str | None  # verbatim quote from the gold chunks; None when unanswerable
    gold_chunk_ids: list[str]
    absent_terms: list[str] = []  # unanswerable only: none of these may occur in the corpus
    area: str
    qtype: QType
    source: Literal["who", "openfda", "pmc"] | None  # where the answer was drafted from
    drafted_by: str

    @model_validator(mode="after")
    def _consistent(self) -> "GoldenItem":
        if self.area not in AREAS:
            raise ValueError(f"unknown area {self.area}")
        if self.answerable:
            if not self.answer or not self.gold_chunk_ids or self.source is None:
                raise ValueError("answerable items need an answer, gold chunks and a source")
            if self.absent_terms:
                raise ValueError("absent_terms are for unanswerable items")
        elif self.answer or self.gold_chunk_ids or not self.absent_terms:
            raise ValueError("unanswerable items need absent_terms and no answer or gold chunks")
        return self


def norm(text: str) -> str:
    """Case- and whitespace-insensitive form used for quote matching."""
    return re.sub(r"\s+", " ", text).strip().lower()


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def shared_ngram(question: str, chunk_text: str, n: int = COPY_NGRAM) -> str | None:
    q, c = words(question), words(chunk_text)
    grams = {tuple(c[i : i + n]) for i in range(len(c) - n + 1)}
    for i in range(len(q) - n + 1):
        if tuple(q[i : i + n]) in grams:
            return " ".join(q[i : i + n])
    return None


def load_items(path: Path = GOLDEN) -> list[GoldenItem]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [GoldenItem.model_validate_json(line) for line in lines if line.strip()]


def load_chunks(path: Path = CORPUS_CHUNKS) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return {(c := json.loads(line))["id"]: c["text"] for line in lines}


def chunks_containing(quote: str, normed_chunks: dict[str, str]) -> list[str]:
    """Ids of chunks whose normalised text contains the quote (pass norm()-ed chunk texts)."""
    needle = norm(quote)
    return sorted(cid for cid, text in normed_chunks.items() if needle in text)


def validate(items: list[GoldenItem], chunks: dict[str, str]) -> list[str]:
    """Problems found; an empty list means the set is valid."""
    problems = []
    ids = Counter(item.id for item in items)
    problems += [f"duplicate id {i}" for i, n in ids.items() if n > 1]
    questions = Counter(norm(item.question) for item in items)
    problems += [f"duplicate question: {q}" for q, n in questions.items() if n > 1]
    normed = {cid: norm(text) for cid, text in chunks.items()}
    for item in items:
        if item.answerable and item.answer is not None:  # the schema guarantees an answer
            for cid in item.gold_chunk_ids:
                if cid not in chunks:
                    problems.append(f"{item.id}: gold chunk {cid} not in the corpus")
                elif norm(item.answer) not in normed[cid]:
                    problems.append(f"{item.id}: answer not found in {cid}")
                elif copied := shared_ngram(item.question, chunks[cid]):
                    problems.append(f"{item.id}: question copies the source ('{copied}')")
            if len(item.answer.split()) < 3:
                problems.append(f"{item.id}: answer quote shorter than 3 words")
        else:
            for term in item.absent_terms:
                hits = [cid for cid, text in normed.items() if norm(term) in text]
                if hits:
                    problems.append(f"{item.id}: absent term '{term}' occurs in {hits[0]}")
    answerable = [i for i in items if i.answerable]
    if len(items) < MIN_ITEMS:
        problems.append(f"{len(items)} items, need >= {MIN_ITEMS}")
    if items and (len(items) - len(answerable)) / len(items) < MIN_UNANSWERABLE_SHARE:
        problems.append(f"unanswerable share below {MIN_UNANSWERABLE_SHARE:.0%}")
    per_area = Counter(i.area for i in answerable)
    problems += [
        f"area {a}: {per_area[a]} answerable items, need >= {MIN_PER_AREA}"
        for a in AREAS
        if per_area[a] < MIN_PER_AREA
    ]
    return problems


def expand(items: list[GoldenItem], chunks: dict[str, str]) -> list[GoldenItem]:
    """Gold chunks = every chunk containing the quote (keeps the drafted chunk first)."""
    normed = {cid: norm(text) for cid, text in chunks.items()}
    out = []
    for item in items:
        if item.answerable and item.answer:
            found = chunks_containing(item.answer, normed)
            ordered = [c for c in item.gold_chunk_ids if c in found]
            ordered += [c for c in found if c not in ordered]
            item = item.model_copy(update={"gold_chunk_ids": ordered or item.gold_chunk_ids})
        out.append(item)
    return out


def write_items(items: list[GoldenItem], path: Path = GOLDEN) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as out:
        for item in sorted(items, key=lambda i: i.id):
            out.write(item.model_dump_json(exclude_defaults=False) + "\n")


def summary(items: list[GoldenItem]) -> str:
    answerable = [i for i in items if i.answerable]
    rows = [
        f"items {len(items)}: answerable {len(answerable)}, "
        f"unanswerable {len(items) - len(answerable)}",
        "by area:   " + json.dumps(Counter(i.area for i in answerable), sort_keys=True),
        "by source: " + json.dumps(Counter(i.source for i in answerable), sort_keys=True),
        "by qtype:  " + json.dumps(Counter(i.qtype for i in answerable), sort_keys=True),
        "gold chunks per item: "
        + json.dumps(Counter(len(i.gold_chunk_ids) for i in answerable), sort_keys=True),
    ]
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the golden set")
    parser.add_argument("--expand", action="store_true", help="rewrite gold ids from the quotes")
    parser.add_argument("--path", type=Path, default=GOLDEN)
    args = parser.parse_args(argv)
    items, chunks = load_items(args.path), load_chunks()
    if args.expand:
        items = expand(items, chunks)
        write_items(items, args.path)
    print(summary(items))
    problems = validate(items, chunks)
    for problem in problems:
        print("PROBLEM", problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
