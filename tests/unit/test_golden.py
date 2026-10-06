"""Golden set: schema, validator rules, gold expansion, review sheet (no corpus needed)."""

import pytest
from pydantic import ValidationError

from evals.golden.golden import (
    MIN_ITEMS,
    GoldenItem,
    expand,
    load_items,
    shared_ngram,
    validate,
)
from evals.golden.review import sheet_problems, stratified_sample

CHUNKS = {
    "fda:x#s0#c0": "Warfarin dose is 2 mg to 5 mg once daily when the genotype is unknown.",
    "fda:x#s0#c1": "Genotype unknown. Warfarin dose is 2 mg to 5 mg once daily. Monitor INR.",
    "pmc:PMC1#s0#c0": "Metformin is first-line therapy for type 2 diabetes in most adults.",
}


def _item(**overrides: object) -> GoldenItem:
    data: dict[str, object] = {
        "id": "g0001",
        "question": "How much warfarin is started if genetics are not known?",
        "answerable": True,
        "answer": "2 mg to 5 mg once daily",
        "gold_chunk_ids": ["fda:x#s0#c0"],
        "area": "anticoagulation",
        "qtype": "dose",
        "source": "openfda",
        "drafted_by": "test",
    }
    data.update(overrides)
    return GoldenItem.model_validate(data)


def test_schema_ties_answers_gold_chunks_and_absent_terms_to_answerability() -> None:
    with pytest.raises(ValidationError):
        _item(answer=None)  # answerable without an answer
    with pytest.raises(ValidationError):
        _item(answerable=False)  # unanswerable but carries an answer
    with pytest.raises(ValidationError):
        _item(area="cardiology")  # unknown area
    unanswerable = _item(
        answerable=False, answer=None, gold_chunk_ids=[], source=None, absent_terms=["abelacimab"]
    )
    assert unanswerable.absent_terms == ["abelacimab"]


def test_validator_flags_missing_quote_copied_wording_and_present_absent_terms() -> None:
    items = [
        _item(id="g0001", answer="10 mg twice daily"),  # quote not in the chunk
        _item(id="g0002", question="Is the Warfarin dose 2 mg to 5 mg once daily here?"),
        _item(
            id="g0003",
            question="Is metformin first line?",
            answerable=False,
            answer=None,
            gold_chunk_ids=[],
            source=None,
            absent_terms=["Metformin"],  # occurs in the corpus, so not unanswerable
            area="diabetes",
            qtype="fact",
        ),
    ]
    problems = "\n".join(validate(items, CHUNKS))
    assert "g0001: answer not found in fda:x#s0#c0" in problems
    assert "g0002: question copies the source" in problems
    assert "g0003: absent term 'Metformin' occurs in pmc:PMC1#s0#c0" in problems
    assert f"need >= {MIN_ITEMS}" in problems


def test_shared_ngram_ignores_case_and_punctuation() -> None:
    assert shared_ngram("Is it 2 mg TO 5 mg, once daily?", CHUNKS["fda:x#s0#c0"])
    assert shared_ngram("How much warfarin to start?", CHUNKS["fda:x#s0#c0"]) is None


def test_expand_adds_overlapping_chunks_and_keeps_the_drafted_one_first() -> None:
    (item,) = expand([_item(gold_chunk_ids=["fda:x#s0#c1"])], CHUNKS)
    assert item.gold_chunk_ids == ["fda:x#s0#c1", "fda:x#s0#c0"]


def test_committed_golden_set_meets_the_task_3_quotas() -> None:
    items = load_items()
    answerable = [i for i in items if i.answerable]
    assert len(items) >= MIN_ITEMS
    assert (len(items) - len(answerable)) / len(items) >= 0.10
    assert len({i.id for i in items}) == len(items)
    assert {i.area for i in answerable} == {
        "hypertension", "diabetes", "anticoagulation", "respiratory", "infections"
    }  # fmt: skip


def test_review_sample_covers_every_stratum_and_needs_complete_rows() -> None:
    items = load_items()
    sample = stratified_sample(items)
    assert len(sample) >= 0.2 * len(items)
    assert {(i.area, i.answerable) for i in sample} == {(i.area, i.answerable) for i in items}
    assert stratified_sample(items) == sample  # seeded
    good = {"id": "g0001", "verdict": "ok", "reviewer": "A. Reviewer", "reviewed_on": "2026-10-07"}
    assert sheet_problems([good], {"g0001"}) == []
    bad = {**good, "verdict": "fix", "notes": ""}
    assert sheet_problems([bad], {"g0001"}) == ["g0001: 'fix' needs a note saying what is wrong"]
