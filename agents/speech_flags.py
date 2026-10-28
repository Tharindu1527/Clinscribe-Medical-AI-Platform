"""Words the speech recogniser was unsure of, on the statements that rely on them (ADR-0027).

SPEC section 4: "low-confidence drug names are highlighted for the doctor, never silently
corrected"; section 8 lists a misheard drug name as a hazard. The Scribe listener sends each turn's
words under its confidence threshold (`voice/scribe.py` `UNSURE_BELOW`, chosen in
`evals/voice/asr_confidence.py`); the API keeps them beside the de-identified transcript, and the
review screen shows them on the statements:
- heard: the statement uses an unsure word of a turn it cites;
- changed: the statement names a drug or clinical term (RxNorm lexicon) that none of its cited
  turns says, while one of those turns has an unsure word: the note writer may have corrected what
  the recogniser heard ("high drugs in" -> "hydroxyzine"), so the doctor checks it against the
  consultation instead of the correction passing unseen.
Only unsure words still present in the de-identified turn are kept: a word de-ID replaced was PHI,
and its flag would put the original into the saved draft. Function words ("a", "and", "to"; the
retrieval stopword list, which keeps negations such as "no" and "not") are not kept: in the first
drafts they were most of the flags and said nothing about the note.
"""

import re
from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Any

from privacy.deid.lexicon import clinical_terms
from retrieval.bm25 import STOPWORDS

WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")


def _words(text: str) -> set[str]:
    return {w.lower() for w in WORD.findall(text)}


@lru_cache(maxsize=1)
def _terms() -> frozenset[str]:
    """Single-word lexicon entries of 5+ letters (shorter ones are mostly everyday words)."""
    return frozenset(t for t in clinical_terms() if re.fullmatch(r"[a-z][a-z-]{4,}", t))


def kept(unsure: Sequence[Mapping[str, Any]], deidentified: str) -> list[dict[str, Any]]:
    """The unsure words still in the de-identified turn, one per word, lowest confidence first;
    function words left out."""
    present = _words(deidentified)
    out: dict[str, dict[str, Any]] = {}
    for u in sorted(unsure, key=lambda u: float(u["confidence"]), reverse=True):
        word = str(u["word"])
        if word.lower() in present and word.lower() not in STOPWORDS:
            out[word.lower()] = {"word": word, "confidence": round(float(u["confidence"]), 3)}
    return sorted(out.values(), key=lambda u: float(u["confidence"]))


def flag_statements(
    statements: Sequence[Mapping[str, Any]],
    transcript: Sequence[str],
    unsure: Sequence[Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    """Per statement: `heard`, the unsure words it uses, and `changed`, None or the terms it names
    that its turns do not say with the unsure words of those turns."""
    out = []
    for statement in statements:
        said = _words(str(statement["text"]))
        turns = sorted({t for t in statement.get("transcript_turns", []) if 0 <= t < len(unsure)})
        heard: dict[str, dict[str, Any]] = {}
        others: dict[str, dict[str, Any]] = {}
        spoken: set[str] = set()
        for turn in turns:
            if turn < len(transcript):
                spoken |= _words(transcript[turn])
            for u in unsure[turn]:
                bucket = heard if str(u["word"]).lower() in said else others
                key = str(u["word"]).lower()
                if key not in bucket or u["confidence"] < bucket[key]["confidence"]:
                    bucket[key] = {**u, "turn": turn}
        terms = sorted((said & _terms()) - spoken)
        changed = {"terms": terms, "unsure": _by_confidence(others)} if terms and others else None
        out.append({"heard": _by_confidence(heard), "changed": changed})
    return out


def _by_confidence(found: Mapping[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(found.values(), key=lambda u: float(u["confidence"]))
