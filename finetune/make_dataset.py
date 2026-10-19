"""Synthetic training data for the de-ID name/place tagger (Phase 5; LoRA fine-tune on Colab).

Clinical-speech sentences with PERSON and LOCATION spans (Faker, seeded; no real people) plus hard
negatives that must stay untouched: eponyms (Parkinson's disease), place-named diseases (Lyme
disease), drug brands and clinical words that look like names. Word-level BIO tags.

  uv run python -m finetune.make_dataset              -> data/finetune/deid_ner_v2/ (round 2)
  uv run python -m finetune.make_dataset --version 1  -> data/finetune/deid_ner/    (round 1)

Round 1 tagged nearly every capitalised sentence start as a name (15 of 80 PHI-free clinical
sentences altered, evals/reports/privacy/deid_lora.md): 9 of its 12 templates start with a name and
it had no PHI-free sentences. Round 2 adds templates with names elsewhere in the sentence and ~40%
PHI-free clinical sentences built from the parts below (none copied from the evaluation sets).
"""

import argparse
import json
import random
import re
import sys
from pathlib import Path

from faker import Faker

DATA = Path(__file__).resolve().parents[1] / "data" / "finetune"
SEED = 20261014
SEED_V2 = 20261019
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
# Round 2: names and places away from the start of the sentence (checked against the held-out sets)
TEMPLATES_V2 = [
    "Spoke to {P} on the ward round about the plan.",
    "the scan was reviewed with {P} this morning.",
    "Discharge summary goes to Dr {P}.",
    "Her GP, Dr {P}, has been informed.",
    "Collateral history from {P}, the patient's partner.",
    "Lives with {P} in a flat in {L}.",
    "Transport arranged back to {L} tomorrow.",
    "Recently returned from a work trip to {L}.",
    "Seen at the walk-in centre in {L} last week.",
    "{P}'s mother also has diabetes.",
    "Booked for a scan at the hospital in {L}.",
    "and {P} said the cough had settled.",
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
# Parts for PHI-free clinical sentences (round 2): every word is tagged O
FINDING_SUBJECTS = [
    "Patient", "Abdomen", "Chest", "Lungs", "Heart sounds", "Skin", "Pulses", "Reflexes",
    "Wound", "Mood", "Appetite", "Sleep", "Gait", "Vision", "Bowels", "Urine output", "Pain",
    "Swelling", "Cough", "Breathing",
]  # fmt: skip
FINDINGS = [
    "normal", "unremarkable", "improving", "stable since the last visit", "worse at night",
    "clear on examination", "soft and non-tender", "reduced on the left", "within normal limits",
    "settling with treatment", "unchanged this week",
]  # fmt: skip
TESTS = [
    "ECG", "CT head", "MRI spine", "CXR", "FBC", "U&E", "LFTs", "TSH", "PSA", "INR", "CRP",
    "eGFR", "HbA1c", "BNP", "ABG", "Echo",
]  # fmt: skip
RESULTS = [
    "normal", "awaited", "repeated today", "within range", "slightly raised",
    "reviewed with the registrar", "sent this morning", "back and unremarkable",
]  # fmt: skip
LABS = [
    ("Sodium", "mmol/L"), ("Potassium", "mmol/L"), ("Creatinine", "micromol/L"),
    ("Haemoglobin", "g/L"), ("Ferritin", "ug/L"), ("Glucose", "mmol/L"),
]  # fmt: skip
MEDICINES = [
    *DRUGS, "Crestor", "Nexium", "Ventolin", "Seretide", "amoxicillin", "ramipril", "bisoprolol",
    "sertraline", "omeprazole", "furosemide", "apixaban",
]  # fmt: skip
DEPARTMENTS = [
    "Cardiology", "Dermatology", "Neurology", "Oncology", "Orthopaedics", "Respiratory",
    "Endocrinology", "Gastroenterology", "Urology", "Rheumatology", "General Medicine",
]  # fmt: skip
UNITS = ["ICU", "HDU", "CCU", "ED", "the day unit", "theatre recovery"]


def words(text: str) -> list[str]:
    return re.findall(r"[\w'.-]+|[^\w\s]", text)


def example(
    fake: Faker, rng: random.Random, templates: list[str] = TEMPLATES
) -> dict[str, list[str]]:
    template = rng.choice(templates)
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


def clinical_sentence(rng: random.Random) -> str:
    """A PHI-free clinical sentence: capitalised starts, acronyms, wards, doses and eponyms."""
    pick = rng.randrange(9)
    if pick == 0:
        return f"{rng.choice(FINDING_SUBJECTS)} {rng.choice(FINDINGS)}."
    if pick == 1:
        return f"{rng.choice(TESTS)} {rng.choice(RESULTS)}."
    if pick == 2:
        return (
            f"BP {rng.randint(95, 180)}/{rng.randint(55, 105)}, pulse {rng.randint(50, 130)}, "
            f"temperature {rng.randint(355, 395) / 10} C."
        )
    if pick == 3:
        name, unit = rng.choice(LABS)
        return f"{name} {rng.randint(3, 160)} {unit}, {rng.choice(['up', 'down', 'unchanged'])}."
    if pick == 4:
        verb = rng.choice(["Started", "Stopped", "Increased", "Reduced", "Continue"])
        return f"{verb} {rng.choice(MEDICINES)} {rng.choice([2.5, 5, 10, 20, 40, 500])} mg daily."
    if pick == 5:
        first, second = rng.sample(MEDICINES, 2)
        return f"Switched from {first} to {second} because of side effects."
    if pick == 6:
        place = rng.choice(["Ward", "Bed", "Bay", "Room", "Theatre"])
        return f"{place} {rng.randint(1, 30)}{rng.choice(['', 'A', 'B'])} is ready."
    if pick == 7:
        how = rng.choice(["Seen in", "Referred to", "Discussed with", "Admitted under"])
        return f"{how} {rng.choice(DEPARTMENTS)} {rng.choice(['today', 'clinic', 'last month'])}."
    if rng.random() < 0.5:
        return f"Transferred from {rng.choice(UNITS)} to the ward overnight."
    return (
        f"Known {rng.choice(NEGATIVES)}, {rng.choice(['stable', 'well controlled', 'reviewed'])}."
    )


def negative(rng: random.Random) -> dict[str, list[str]]:
    tokens = words(clinical_sentence(rng))
    return {"tokens": tokens, "tags": ["O"] * len(tokens)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", type=int, choices=(1, 2), default=2)
    version = parser.parse_args(argv).version
    seed = SEED if version == 1 else SEED_V2
    out = DATA / ("deid_ner" if version == 1 else "deid_ner_v2")
    fake, rng = Faker("en_US"), random.Random(seed)
    Faker.seed(seed)
    out.mkdir(parents=True, exist_ok=True)
    for split, n in (("train", 4000), ("dev", 500), ("test", 500)):
        if version == 1:
            rows = [example(fake, rng) for _ in range(n)]
        else:  # 60% with names or places (both template sets), 40% PHI-free clinical sentences
            templates = TEMPLATES + TEMPLATES_V2
            rows = [
                example(fake, rng, templates) if rng.random() < 0.6 else negative(rng)
                for _ in range(n)
            ]
        (out / f"{split}.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
        )
        print(f"{split}: {n} sentences -> {out / f'{split}.jsonl'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
