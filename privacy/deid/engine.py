"""De-identification: detect PHI, replace it with consistent surrogates, return DeidentifiedText."""

import re
from dataclasses import dataclass

from presidio_analyzer import AnalyzerEngine, RecognizerRegistry, RecognizerResult
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_analyzer.predefined_recognizers import SpacyRecognizer

from privacy.deid.recognizers import PATTERNS, RegexRecognizer
from privacy.deid.store import SurrogateStore
from privacy.deid.types import DeidentifiedText, issue

NER_TYPES = ("PERSON", "LOCATION")
ALL_TYPES = (*NER_TYPES, *PATTERNS)
MIN_SCORE = 0.5
SURROGATE_RE = re.compile(r"\b(?:" + "|".join(ALL_TYPES) + r")_\d+\b")


@dataclass(frozen=True)
class Replacement:
    entity: str
    surrogate: str


@dataclass(frozen=True)
class DeidResult:
    text: DeidentifiedText
    replacements: list[Replacement]


def build_analyzer(spacy_model: str) -> AnalyzerEngine:
    """Presidio with an explicit recogniser list: spaCy for names/places, regexes for the rest."""
    nlp_engine = NlpEngineProvider(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": spacy_model}],
        }
    ).create_engine()
    registry = RecognizerRegistry(supported_languages=["en"])
    registry.add_recognizer(SpacyRecognizer(supported_entities=list(NER_TYPES)))
    registry.add_recognizer(RegexRecognizer())
    return AnalyzerEngine(nlp_engine=nlp_engine, registry=registry, supported_languages=["en"])


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
