"""Tell clinical terms apart from names and places, so de-ID does not damage clinical meaning.

Applied to PERSON/LOCATION matches (never to structured identifiers); the eponym rule only to
spaCy's statistical guesses, never to cue-based ones such as "Dr. Parkinson":
- eponyms and place-named conditions: a capitalised word directly followed by a clinical head noun
  ("Hodgkin lymphoma", "Murphy's sign", "Foley catheter", "West Nile virus") is a term, not PHI;
- drug and department names from privacy/deid/resources/clinical_lexicon.txt (RxNorm, person
  names removed): a span that is exactly one of them ("Coumadin", "Cardiology") is not PHI.
Measured in evals/privacy/deid_eval.py (over-redaction on PHI-free clinical sentences).
"""

import re
from functools import lru_cache
from pathlib import Path

LEXICON_FILE = Path(__file__).resolve().parent / "resources" / "clinical_lexicon.txt"

HEAD_NOUNS = (
    "disease|diseases|syndrome|syndromes|sign|signs|lymphoma|sarcoma|carcinoma|tumou?r|cyst|ulcer|"
    "catheter|tube|line|needle|monitor|virus|fever|palsy|esophagus|oesophagus|phenomenon|score|scale|"
    "maneuver|manoeuvre|test|reflex|procedure|operation|criteria|classification|fracture|deformity|"
    "contracture|triad|law|equation|formula|index|node|nodes|sputum|stools?|urine|discharge|"
    "blood|cells?|count|spots?|lesions?|anomaly|malformation|aneurysm|hernia|block|repair|"
    "encephalopathy|dementia|anemia|anaemia|thyroiditis|neuralgia|neuropathy|myopathy|dystrophy"
)
# At most one modifier from a closed list may sit between the term and its head noun
# ("Rocky Mountain spotted fever", "Burkitt cell lymphoma"). An open slot would wrongly turn
# "John Smith has fever" into a term and leak the name.
MODIFIERS = "spotted|cell|type|associated|related|like|hemorrhagic|haemorrhagic"
_FOLLOWED_BY_HEAD_NOUN = re.compile(
    rf"^(?:'s|s'|')?\s+(?:(?:{MODIFIERS})\s+)?(?:{HEAD_NOUNS})\b", re.IGNORECASE
)


@lru_cache(maxsize=1)
def clinical_terms() -> frozenset[str]:
    lines = LEXICON_FILE.read_text(encoding="utf-8").splitlines()
    return frozenset(line.strip() for line in lines if line.strip() and not line.startswith("#"))


def is_clinical_term(text: str, start: int, end: int) -> bool:
    """True if text[start:end] (a NER guess) is part of a clinical term, not a name or place."""
    span = text[start:end].strip()
    if span.lower() in clinical_terms():
        return True
    return bool(_FOLLOWED_BY_HEAD_NOUN.match(text[end:]))
