"""Build the clinical-term lexicon that stops de-ID from redacting drug and department names.

Usage: uv run python -m scripts.fetch_lexicons
Sources: RxNorm brand names (BN) and ingredients (IN) via NLM's RxNav REST API (public data;
recorded in data/LICENSES.md), plus a short list of hospital departments. Entries that are also
person names in Faker's en_US lists are removed (Grace, Hope, Brown). Names outside those lists can
remain (e.g. the brand "Allegra"), so a lone, cue-less mention of such a name is not redacted; any
cue ("Mrs. Allegra ...") still is. Known limitation, recorded in ADR-0004.
Output: privacy/deid/resources/clinical_lexicon.txt (sorted, lower-case, committed).
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
from faker.providers.person.en_US import Provider as PersonProvider

RXNAV = "https://rxnav.nlm.nih.gov/REST/allconcepts.json"
OUT = (
    Path(__file__).resolve().parents[1] / "privacy" / "deid" / "resources" / "clinical_lexicon.txt"
)
DEPARTMENTS = [
    "cardiology",
    "oncology",
    "neurology",
    "radiology",
    "pediatrics",
    "paediatrics",
    "surgery",
    "medicine",
    "orthopedics",
    "orthopaedics",
    "dermatology",
    "psychiatry",
    "urology",
    "nephrology",
    "gastroenterology",
    "endocrinology",
    "rheumatology",
    "hematology",
    "haematology",
    "pulmonology",
    "respiratory",
    "obstetrics",
    "gynecology",
    "gynaecology",
    "ophthalmology",
    "otolaryngology",
    "maternity",
    "pharmacy",
    "physiotherapy",
    "rehabilitation",
    "pathology",
    "anesthesia",
    "anaesthesia",
    "geriatrics",
    "neonatology",
    "infectious",
    "diseases",
    "immunology",
    "allergy",
    "oncology",
]


def rxnorm_names(tty: str) -> list[str]:
    response = httpx.get(RXNAV, params={"tty": tty}, timeout=120)
    response.raise_for_status()
    return [c["name"] for c in response.json()["minConceptGroup"]["minConcept"]]


def person_names() -> set[str]:
    names: set[str] = set()
    for attr in ("first_names", "first_names_female", "first_names_male", "last_names"):
        names.update(n.lower() for n in getattr(PersonProvider, attr, ()))
    return names


def build(brands: list[str], ingredients: list[str], people: set[str]) -> list[str]:
    terms = {t.strip().lower() for t in [*brands, *ingredients, *DEPARTMENTS]}
    # Long chemical names never collide with names or places, and only bloat the file
    terms = {t for t in terms if 3 <= len(t) <= 40 and any(ch.isalpha() for ch in t)}
    return sorted(terms - people)


def main() -> int:
    terms = build(rxnorm_names("BN"), rxnorm_names("IN"), person_names())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"# Clinical terms that are not PHI (drugs, ingredients, departments): {len(terms)}.\n"
        f"# Built {datetime.now(UTC):%Y-%m-%d} by scripts/fetch_lexicons.py from RxNorm\n"
        "# (NLM RxNav API); person names removed.\n"
        "# Regenerate with `uv run python -m scripts.fetch_lexicons`.\n"
    )
    OUT.write_text(header + "\n".join(terms) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {len(terms)} terms to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
