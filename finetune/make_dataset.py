"""Synthetic training data for the de-ID name/place tagger (Phase 5; LoRA fine-tune on Colab).

Clinical-speech sentences with PERSON and LOCATION spans (Faker, seeded; no real people) plus hard
negatives that must stay untouched: eponyms (Parkinson's disease), place-named diseases (Lyme
disease), drug brands and clinical words that look like names. Word-level BIO tags.

  uv run python -m finetune.make_dataset      -> data/finetune/deid_ner/{train,dev,test}.jsonl
"""

import json
import random
import re
import sys
from pathlib import Path

from faker import Faker

OUT = Path(__file__).resolve().parents[1] / "data" / "finetune" / "deid_ner"
SEED = 20261014
TEMPLATES = [
    "{P} came in today with a cough for three days.",
    "This is Dr. {P}, I'm seeing {P} for follow-up.",
    "{P} lives in {L} and works in {L}.",
    "My daughter {P} drove me here from {L}.",
    "She was referred by Dr. {P} at the clinic in {L}.",
    "{P} was originally from {L} before moving to {L}.",
    "Please call {P}, her husband, if anything changes.",
    "We discussed {N} with {P} and her son {P}.",
    "{P} has a history of {N} and takes {D} daily.",
    "The patient, {P}, reports dizziness since visiting {L}.",
    "Hi {P}, I'm the nurse, Dr. {P} will be with you shortly.",
    "{P} and {P} both came to the appointment from {L}.",
]
NEGATIVES = [
    "Parkinson's disease",
    "Crohn's disease",
    "Hashimoto's thyroiditis",
    "Lyme disease",
    "Addison's disease",
    "Bell's palsy",
    "Down syndrome",
    "Cushing's syndrome",
    "West Nile virus",
    "Graves' disease",
    "Alzheimer's disease",
    "Huntington's disease",
]
DRUGS = ["Lasix", "Eliquis", "Januvia", "Xarelto", "Allegra", "Lipitor", "Norvasc", "Zoloft"]


def words(text: str) -> list[str]:
    return re.findall(r"[\w'.-]+|[^\w\s]", text)


def example(fake: Faker, rng: random.Random) -> dict[str, list[str]]:
    template = rng.choice(TEMPLATES)
    tokens: list[str] = []
    tags: list[str] = []
    for part in re.split(r"(\{[PLND]\})", template):
        if part == "{P}":
            span, label = rng.choice([fake.first_name(), fake.name(), fake.last_name()]), "PERSON"
        elif part == "{L}":
            span, label = rng.choice([fake.city(), fake.state(), fake.street_name()]), "LOCATION"
        elif part == "{N}":
            span, label = rng.choice(NEGATIVES), None
        elif part == "{D}":
            span, label = rng.choice(DRUGS), None
        else:
            span, label = part, None
        piece = words(span)
        tokens += piece
        tags += [("B-" if i == 0 else "I-") + label if label else "O" for i in range(len(piece))]
    return {"tokens": tokens, "tags": tags}


def main() -> int:
    fake, rng = Faker("en_US"), random.Random(SEED)
    Faker.seed(SEED)
    OUT.mkdir(parents=True, exist_ok=True)
    for split, n in (("train", 4000), ("dev", 500), ("test", 500)):
        rows = [example(fake, rng) for _ in range(n)]
        (OUT / f"{split}.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
        )
        print(f"{split}: {n} sentences -> {OUT / f'{split}.jsonl'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
