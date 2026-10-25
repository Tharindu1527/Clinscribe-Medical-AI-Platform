"""Subject grounding (ADR-0018): unseen terms, drugs named in the cited sources, and the
guidelines-mcp tool that serves both."""

from typing import Any

import pytest

from mcp_servers.guidelines_mcp.server import build_server
from privacy.deid.types import DeidentifiedText, issue
from retrieval.graph.lexicon import DrugLexicon
from retrieval.grounding import Grounding, spellings
from tests.unit.test_mcp_servers import call

pytestmark = pytest.mark.unit
CHUNKS = [
    {
        "id": "fda:oz#s7#c12",
        "title": "Ozempic (semaglutide) prescribing information",
        "section": "Adverse reactions",
        "text": "The most common adverse reactions are nausea, vomiting and diarrhea.",
    },
    {
        "id": "fda:w#s1#c0",
        "title": "Warfarin label",
        "section": "Dosage",
        "text": "The usual starting dose of warfarin is 2 to 5 mg daily. Nebulized drugs differ.",
    },
    {
        "id": "fda:ap#s2#c0",
        "title": "Eliquis (apixaban)",
        "section": "Dosage",
        "text": "Apixaban 5 mg twice daily.",
    },
]
LEXICON = DrugLexicon(
    [
        {"ddinter_id": "D1", "name": "Warfarin"},
        {"ddinter_id": "D2", "name": "Apixaban", "brands": ["Eliquis"]},
        {"ddinter_id": "D3", "name": "Semaglutide", "brands": ["Ozempic"]},
        {"ddinter_id": "D4", "name": "Clarithromycin"},
    ]
)
ENGLISH = {  # a stand-in for the spaCy vocabulary: the ordinary words these questions use
    "gastrointestinal", "effect", "cause", "starting", "tighter", "control", "about",
    "different", "drugs", "person", "location", "street", "address",
}  # fmt: skip


@pytest.fixture
def grounding() -> Grounding:
    return Grounding(CHUNKS, ENGLISH.__contains__, LEXICON)


def test_a_word_no_source_uses_and_no_english_word_is_unseen(grounding: Grounding) -> None:
    assert grounding.unseen_terms("Which gastrointestinal effects does mazdutide cause?") == [
        "mazdutide"
    ]
    assert grounding.unseen_terms("What is the starting dose of warfarin?") == []
    assert grounding.unseen_terms("Did tighter control help?") == []  # an English word
    # the filters can be switched off, as the evaluation's variants do
    assert grounding.unseen_terms("Did tighter control help?", english=False) == [
        "tighter",
        "control",
    ]


def test_a_deid_surrogate_is_never_an_unseen_term() -> None:
    strict = Grounding(CHUNKS, lambda word: False, LEXICON)  # no word counts as English
    assert strict.unseen_terms("PERSON_1 at STREET_ADDRESS_2: mazdutide?") == ["mazdutide"]


def test_uk_spellings_of_corpus_words_are_not_unseen(grounding: Grounding) -> None:
    assert "nebulized" in spellings("nebulised")
    assert "hemoglobin" in spellings("haemoglobin")
    assert grounding.unseen_terms("Are nebulised drugs different?") == []
    assert grounding.unseen_terms("Are nebulised drugs different?", fold=False) == ["nebulised"]


def test_a_drug_the_question_names_must_be_named_in_a_cited_source(grounding: Grounding) -> None:
    question = "What is the usual dose of apixaban?"
    assert grounding.missing_drugs(question, ["fda:w#s1#c0"]) == ["Apixaban"]
    assert grounding.missing_drugs(question, ["fda:ap#s2#c0"]) == []
    assert grounding.missing_drugs("Is Eliquis given twice daily?", ["fda:ap#s2#c0"]) == []
    assert grounding.missing_drugs("What dose should be used?", ["fda:w#s1#c0"]) == []  # no drug


def test_a_ddinter_fact_names_its_two_drugs(grounding: Grounding) -> None:
    question = "Does clarithromycin interact with warfarin?"
    assert grounding.missing_drugs(question, ["graph:ddinter:Clarithromycin|Warfarin"]) == []
    assert grounding.missing_drugs(question, ["fda:w#s1#c0"]) == ["Clarithromycin"]


class NoSearch:
    def search(self, query: DeidentifiedText, k: int = 10) -> list[Any]:
        raise AssertionError("check_grounding does not search")


def test_the_tool_checks_the_deidentified_question(grounding: Grounding) -> None:
    seen: list[str] = []

    def deidentify(text: str) -> DeidentifiedText:
        seen.append(text)
        return issue(text.replace("Zbigniewski", "PERSON_1"), "deid-service")

    chunks = {c["id"]: c for c in CHUNKS}
    server = build_server(NoSearch(), chunks, deidentify, grounding)
    question = "Mr Zbigniewski asks about mazdutide and apixaban"
    error, result = call(
        server, "check_grounding", {"question": question, "cited": ["fda:w#s1#c0"]}
    )
    assert not error
    assert seen == [question]
    assert result == {"unseen_terms": ["mazdutide"], "missing_drugs": ["Apixaban"]}
