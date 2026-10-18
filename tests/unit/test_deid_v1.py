"""De-ID v1: names and places from context cues, and clinical terms left intact (synthetic text)."""

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from privacy.deid.engine import Deidentifier, build_analyzer
from privacy.deid.lexicon import clinical_terms, is_clinical_term
from privacy.deid.store import InMemoryStore


@pytest.fixture(scope="module")
def deid() -> Deidentifier:
    store = InMemoryStore(SecretStr(Fernet.generate_key().decode()))
    return Deidentifier(build_analyzer("en_core_web_md"), store)


@pytest.mark.parametrize(
    ("text", "secrets"),
    [
        ("Daughter Morgan Marsh at bedside.", ["Morgan", "Marsh"]),
        ("Tiffany Holloway (MRN 00482913) seen today.", ["Tiffany", "Holloway"]),
        ("Mrs. Taylor Smith reports dizziness.", ["Taylor", "Smith"]),
        ("Lives at 12 Oak Lane, Jacquelineland, MA 02115.", ["Jacquelineland"]),
        ("Referred by Dr. Ada Jones from New Barry.", ["Barry", "Ada", "Jones"]),
        ("She moved to Port Monicaburgh last year.", ["Monicaburgh"]),
    ],
)
def test_cued_names_and_places_are_replaced(
    deid: Deidentifier, text: str, secrets: list[str]
) -> None:
    out = deid.deidentify(text, "enc-cues").text.text
    assert all(s not in out for s in secrets), out


@pytest.mark.parametrize(
    "text",
    [
        "Biopsy confirmed Hodgkin lymphoma, stage II.",
        "A Foley catheter was placed for urinary retention.",
        "Murphy's sign was positive on examination.",
        "West Nile virus serology is pending.",
        "Rocky Mountain spotted fever considered after the tick bite.",
        "Changed from Coumadin to Eliquis last year.",
        "Brown sputum for three days with fever.",
    ],
)
def test_clinical_terms_are_left_intact(deid: Deidentifier, text: str) -> None:
    result = deid.deidentify(text, "enc-terms")
    assert result.text.text == text
    assert result.replacements == []


@pytest.mark.parametrize(
    ("text", "secrets"),
    [
        # as Deepgram wrote a spoken date of birth in a PriMock57 consultation
        ("Uhh, 21 12 at 1986.", ["21 12 at 1986"]),
        ("My date of birth is 4 10 84.", ["4 10 84"]),
        ("Born on the 21st of December 1986.", ["21st of December"]),
        ("DOB 21.12.1986, seen today.", ["21.12.1986"]),
        ("Number 1 London Street, N W 36 P Q.", ["N W 36 P Q"]),
        ("Lives at NW3 6PQ with her sister.", ["NW3 6PQ"]),
        ("My postcode is S W 1 A 1 A A.", ["S W 1 A 1 A A"]),
    ],
)
def test_spoken_dates_and_uk_postcodes_from_speech_recognition_are_replaced(
    deid: Deidentifier, text: str, secrets: list[str]
) -> None:
    out = deid.deidentify(text, "enc-spoken").text.text
    assert all(s not in out for s in secrets), out


@pytest.mark.parametrize(
    "text",
    [
        "BP 140 90 at rest, pulse 72.",
        "Type 2 diabetes since 2019, HbA1c 48 mmol/mol.",
        "Take 1 or 2 tablets, up to 8 a day.",
        "Started metformin 500 mg in 2021 for T2DM.",
        "CD4 count 350, viral load undetectable.",
        "Vitamin B12 level 250 ng/L in 2024.",
    ],
)
def test_numbers_and_codes_like_dates_or_postcodes_are_kept(deid: Deidentifier, text: str) -> None:
    assert deid.deidentify(text, "enc-kept").text.text == text


def test_a_cue_beats_the_eponym_rule(deid: Deidentifier) -> None:
    # A real clinician who shares an eponym's name is still a person
    out = deid.deidentify("Seen by Dr. Parkinson today.", "enc-dr").text.text
    assert "Parkinson" not in out


def test_open_words_between_name_and_head_noun_do_not_hide_a_name() -> None:
    text = "John Smith has fever."
    assert not is_clinical_term(text, 0, len("John Smith"))  # "has" is not a closed modifier
    assert is_clinical_term("Rocky Mountain spotted fever", 0, len("Rocky Mountain"))


def test_lexicon_contains_drugs_but_not_common_names() -> None:
    terms = clinical_terms()
    assert {"lipitor", "coumadin", "eliquis", "warfarin", "cardiology"} <= terms
    assert not {"grace", "hope", "brown"} & terms  # person names were removed when it was built
