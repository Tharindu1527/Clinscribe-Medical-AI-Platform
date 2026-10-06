"""Seeded sample of corpus chunks to draft golden questions from (task 3 drafting aid).

Chunks are grouped by clinical area and source; only passages that state something checkable
(a number, a dose, a recommendation, a contraindication, an interaction) are kept. The drafter
reads them, writes a question in their own words and quotes the answer span.

Usage: uv run python -m evals.golden.candidates
  -> data/golden/candidates/<area>.jsonl (git-ignored)
"""

import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "data" / "corpus"
OUT = ROOT / "data" / "golden" / "candidates"
SEED = 42
PER_AREA_SOURCE = {"pmc": 30, "openfda": 15, "who": 15}  # ~1.5x the drafting quota
# Chunks per document: low for the many reviews and labels, high for WHO (one guideline per area)
PER_DOC = {"pmc": 2, "openfda": 2, "who": 15}

AREAS = ("hypertension", "diabetes", "anticoagulation", "respiratory", "infections")
TOPIC_AREA = {
    "hypertension": "hypertension",
    "hypertension management": "hypertension",
    "type 2 diabetes": "diabetes",
    "type 2 diabetes pharmacotherapy": "diabetes",
    "atrial fibrillation anticoagulation": "anticoagulation",
    "direct oral anticoagulants": "anticoagulation",
    "warfarin drug interactions": "anticoagulation",
    "asthma management": "respiratory",
    "COPD management": "respiratory",
    "common infections": "infections",
    "community-acquired pneumonia": "infections",
    "urinary tract infection treatment": "infections",
    "antibiotic prescribing primary care": "infections",
}
AREA_DRUGS = {  # the openFDA drug list in config/corpus.yaml, grouped by area
    "hypertension": ("lisinopril", "enalapril", "losartan", "valsartan", "amlodipine",
                     "hydrochlorothiazide", "chlorthalidone", "metoprolol", "bisoprolol",
                     "spironolactone"),
    "diabetes": ("metformin", "empagliflozin", "dapagliflozin", "sitagliptin", "semaglutide",
                 "liraglutide", "glipizide", "glargine", "pioglitazone"),
    "anticoagulation": ("warfarin", "apixaban", "rivaroxaban", "dabigatran", "edoxaban",
                        "amiodarone", "digoxin", "diltiazem"),
    "respiratory": ("albuterol", "budesonide", "fluticasone", "salmeterol", "formoterol",
                    "tiotropium", "montelukast", "prednisone"),
    "infections": ("amoxicillin", "azithromycin", "clarithromycin", "doxycycline",
                   "ciprofloxacin", "levofloxacin", "nitrofurantoin", "sulfamethoxazole",
                   "cephalexin", "ceftriaxone", "fluconazole", "metronidazole"),
}  # fmt: skip
DRUG_AREA = {drug: area for area, drugs in AREA_DRUGS.items() for drug in drugs}
# The WHO NCD package (PEN) covers several areas; its chunks are routed by their own words.
AREA_WORDS = {
    "hypertension": r"blood pressure|hypertens",
    "diabetes": r"diabet|glucose|HbA1c|insulin|metformin",
    "anticoagulation": r"anticoag|warfarin|atrial fibrillation",
    "respiratory": r"asthma|COPD|inhal|wheez|bronch",
    "infections": r"infection|antibiotic|pneumonia",
}
CHECKABLE = re.compile(
    r"\d|\b(recommend\w*|should|contraindicat\w*|avoid|first[- ]line|dose|interact\w*|"
    r"risk|increase[sd]?|reduce[sd]?)\b",
    re.IGNORECASE,
)
SKIP_SECTION = re.compile(
    r"method|search strateg|study selection|limitation|future|conclusion|author|introduction|"
    r"background|^body$|figure|table|framework|annex|page \d+$",
    re.IGNORECASE,
)


def area_of(chunk: dict[str, str]) -> str | None:
    if chunk["source"] == "openfda":
        match = re.search(r"\(([^)]+)\)", chunk["title"])
        words = (match.group(1) if match else chunk["title"]).lower().split()
        return next((DRUG_AREA[w] for w in words if w in DRUG_AREA), None)
    if chunk["topic"] in TOPIC_AREA:
        return TOPIC_AREA[chunk["topic"]]
    scores = {a: len(re.findall(p, chunk["text"], re.IGNORECASE)) for a, p in AREA_WORDS.items()}
    best = max(scores, key=lambda a: scores[a])
    return best if scores[best] >= 2 else None


def usable(chunk: dict[str, str]) -> bool:
    words = len(chunk["text"].split())
    return (
        80 <= words <= 300
        and "[?]" not in chunk["text"]
        and "[formula]" not in chunk["text"]
        and not (chunk["source"] == "pmc" and SKIP_SECTION.search(chunk["section"]))
        and len(CHECKABLE.findall(chunk["text"])) >= 3
    )


def sample(chunks: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for chunk in chunks:
        area = area_of(chunk)
        if area and usable(chunk):
            groups[(area, chunk["source"])].append(chunk)
    rng = random.Random(SEED)
    picked: dict[str, list[dict[str, str]]] = {area: [] for area in AREAS}
    for (area, source), group in sorted(groups.items()):
        # a per-document cap, so one long review cannot dominate an area
        rng.shuffle(group)
        per_doc: dict[str, int] = defaultdict(int)
        for chunk in group:
            if len([c for c in picked[area] if c["source"] == source]) >= PER_AREA_SOURCE[source]:
                break
            if per_doc[chunk["doc_id"]] < PER_DOC[source]:
                per_doc[chunk["doc_id"]] += 1
                picked[area].append(chunk)
    return picked


def main() -> int:
    lines = (CORPUS / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
    picked = sample([json.loads(line) for line in lines])
    OUT.mkdir(parents=True, exist_ok=True)
    for area, chunks in picked.items():
        with (OUT / f"{area}.jsonl").open("w", encoding="utf-8", newline="\n") as out:
            for chunk in chunks:
                out.write(json.dumps(chunk, ensure_ascii=False) + "\n")
        by_source = {s: sum(c["source"] == s for c in chunks) for s in PER_AREA_SOURCE}
        print(f"{area:16} {len(chunks):3} {by_source}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
