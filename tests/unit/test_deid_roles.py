"""A model's name guess that is only a role word ("Patient", "Wife") is not PHI (ADR-0029). The
fine-tuned tagger made these guesses; a fake recogniser that takes every first word for a name
stands in for it here, so CI needs no model (evals/privacy/role_words.py measures the tagger)."""

import pytest
from cryptography.fernet import Fernet
from presidio_analyzer import EntityRecognizer, RecognizerResult
from presidio_analyzer.nlp_engine import NlpArtifacts
from pydantic import SecretStr

import privacy.deid.engine as engine
from privacy.deid.engine import Deidentifier, build_analyzer
from privacy.deid.store import InMemoryStore

pytestmark = pytest.mark.unit


class _FirstWordIsAName(EntityRecognizer):
    def __init__(self) -> None:
        super().__init__(supported_entities=["PERSON"], name="first-word")

    def load(self) -> None:
        return None

    def analyze(
        self, text: str, entities: list[str], nlp_artifacts: NlpArtifacts | None = None
    ) -> list[RecognizerResult]:
        end = len(text.split()[0].rstrip(",."))
        metadata = {RecognizerResult.RECOGNIZER_NAME_KEY: "first-word"}
        return [RecognizerResult("PERSON", 0, end, 0.85, recognition_metadata=metadata)]


@pytest.fixture(scope="module")
def deid() -> Deidentifier:
    analyzer = build_analyzer("en_core_web_md", spacy_ner=False, extra=[_FirstWordIsAName()])
    return Deidentifier(analyzer, InMemoryStore(SecretStr(Fernet.generate_key().decode())))


@pytest.mark.parametrize(
    "text",
    [
        "Patient has been really thirsty for about three weeks.",
        "Patient's mother reports a fever overnight.",
        "Patients with this rash usually recover within a week.",
        "Wife has noticed he is more forgetful lately.",
        "Registrar requested a chest X-ray before discharge.",
    ],
)
def test_a_role_word_alone_is_not_replaced(deid: Deidentifier, text: str) -> None:
    assert deid.deidentify(text, "enc-roles").text.text == text


def test_names_are_still_replaced_next_to_a_role_word_and_after_a_cue(deid: Deidentifier) -> None:
    assert deid.deidentify("Jane has been thirsty.", "enc-roles").text.text.startswith("PERSON_")
    assert "Son" not in deid.deidentify("Mr Son reviewed the X-ray.", "enc-roles").text.text


def test_without_the_filter_the_guess_replaces_the_role_word(
    deid: Deidentifier, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine, "ROLE_WORDS", frozenset())
    out = deid.deidentify("Patient has been really thirsty.", "enc-control").text.text
    assert out.startswith("PERSON_")
