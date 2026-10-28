"""De-identification: detect PHI, replace it with consistent surrogates, return DeidentifiedText."""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from presidio_analyzer import (
    AnalyzerEngine,
    EntityRecognizer,
    RecognizerRegistry,
    RecognizerResult,
)
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_analyzer.predefined_recognizers import SpacyRecognizer

from privacy.deid.lexicon import clinical_terms, is_clinical_term
from privacy.deid.recognizers import CONTEXT_PATTERNS, CUE_SCORE, PATTERNS, RegexRecognizer
from privacy.deid.store import SurrogateStore
from privacy.deid.types import DeidentifiedText, issue

NER_TYPES = ("PERSON", "LOCATION")
CONTEXT_RECOGNIZER = "clinscribe-context"
ALL_TYPES = (*NER_TYPES, *PATTERNS)
MIN_SCORE = 0.5
SURROGATE_RE = re.compile(r"\b(?:" + "|".join(ALL_TYPES) + r")_\d+\b")
# A person's role in care, never an identifier on its own: the fine-tuned tagger took "Patient" at
# the start of a note sentence for a name (ADR-0029; evals/privacy/role_words.py). Only a span that
# is exactly one of these is dropped, so "Patient Jane Smith" still loses the name.
ROLE_WORDS = frozenset(
    {
        "patient", "patients", "doctor", "nurse", "clinician", "gp", "consultant", "registrar",
        "midwife", "pharmacist", "physiotherapist", "physio", "carer", "mother", "father", "mum",
        "dad", "wife", "husband", "partner", "daughter", "son", "sister", "brother", "parent",
        "parents", "child", "baby", "family",
    }
)  # fmt: skip
_POSSESSIVE = re.compile(r"(?:'s|s'|')$")


@dataclass(frozen=True)
class Replacement:
    entity: str
    surrogate: str


@dataclass(frozen=True)
class DeidResult:
    text: DeidentifiedText
    replacements: list[Replacement]


def build_analyzer(
    spacy_model: str,
    *,
    spacy_ner: bool = True,
    extra: Sequence[EntityRecognizer] = (),
) -> AnalyzerEngine:
    """Presidio with an explicit recogniser list: spaCy for names/places, regexes for the rest.

    `spacy_ner=False` and `extra` swap in another name/place recogniser for comparison
    (evals/privacy/lora_eval.py); spaCy still tokenises the text either way."""
    nlp_engine = NlpEngineProvider(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": spacy_model}],
        }
    ).create_engine()
    registry = RecognizerRegistry(supported_languages=["en"])
    if spacy_ner:
        registry.add_recognizer(SpacyRecognizer(supported_entities=list(NER_TYPES)))
    for recognizer in extra:
        registry.add_recognizer(recognizer)
    registry.add_recognizer(RegexRecognizer())
    registry.add_recognizer(
        RegexRecognizer(CONTEXT_PATTERNS, name=CONTEXT_RECOGNIZER, score=CUE_SCORE)
    )
    return AnalyzerEngine(nlp_engine=nlp_engine, registry=registry, supported_languages=["en"])


def analyzer_for(ner: str, spacy_model: str, tagger_path: str = "") -> AnalyzerEngine:
    """The service's analyzer for `DEID_NER`: "spacy" (default) or "tagger", the fine-tuned
    name/place model instead of spaCy's NER (ADR-0014; spaCy still tokenises). Needs torch."""
    if ner == "spacy":
        return build_analyzer(spacy_model)
    if ner == "tagger":
        from privacy.deid.tagger import TaggerRecognizer  # torch only when chosen

        return build_analyzer(spacy_model, spacy_ner=False, extra=[TaggerRecognizer(tagger_path)])
    raise ValueError(f"DEID_NER must be spacy or tagger, not {ner!r}")


def _not_phi(text: str, result: RecognizerResult) -> bool:
    """Drop name/place spans that are clinical terms (de-ID v1, see privacy/deid/lexicon.py) or,
    for a model's guess, a role word alone ("Patient", "Wife's").

    Model guesses (spaCy, the tagger) also pass the eponym rule ("Hodgkin lymphoma") and the role
    words; cue-based matches only the exact lexicon check ("Sent from Cardiology"), so a cue such
    as "Dr. Parkinson" or "Mr Son" still redacts the name.
    """
    if result.entity_type not in NER_TYPES:
        return False
    span = text[result.start : result.end].strip().lower()
    if span in clinical_terms():
        return True
    recognizer = (result.recognition_metadata or {}).get(RecognizerResult.RECOGNIZER_NAME_KEY)
    if recognizer == CONTEXT_RECOGNIZER:  # "Mr Son": after a cue a role word is a surname
        return False
    return _POSSESSIVE.sub("", span) in ROLE_WORDS or is_clinical_term(
        text, result.start, result.end
    )


def _select(results: list[RecognizerResult]) -> list[RecognizerResult]:
    """Keep non-overlapping spans, preferring higher confidence, then longer spans."""
    chosen: list[RecognizerResult] = []
    for result in sorted(results, key=lambda r: (-r.score, -(r.end - r.start), r.start)):
        if result.score < MIN_SCORE:
            continue
        if all(result.end <= c.start or result.start >= c.end for c in chosen):
            chosen.append(result)
    return sorted(chosen, key=lambda r: r.start)


class Deidentifier:
    def __init__(self, analyzer: AnalyzerEngine, store: SurrogateStore) -> None:
        self._analyzer = analyzer
        self._store = store

    def deidentify(self, text: str, encounter_id: str) -> DeidResult:
        results = self._analyzer.analyze(text=text, language="en", entities=list(ALL_TYPES))
        results = [r for r in results if not _not_phi(text, r)]
        pieces: list[str] = []
        replacements: list[Replacement] = []
        cursor = 0
        for result in _select(results):
            value = text[result.start : result.end]
            if SURROGATE_RE.fullmatch(value.strip()):
                continue  # already a surrogate (text de-identified twice)
            surrogate = self._store.surrogate_for(encounter_id, result.entity_type, value)
            pieces.extend([text[cursor : result.start], surrogate])
            replacements.append(Replacement(result.entity_type, surrogate))
            cursor = result.end
        pieces.append(text[cursor:])
        return DeidResult(issue("".join(pieces), source="deid-service"), replacements)

    def reidentify(self, text: str, encounter_id: str) -> str:
        """Restore originals. Only for the treating doctor's own screen (never logs or LLMs)."""

        def restore(match: re.Match[str]) -> str:
            original = self._store.original_for(encounter_id, match.group(0))
            return original if original is not None else match.group(0)

        return SURROGATE_RE.sub(restore, text)
