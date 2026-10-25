"""Prompt building and reply checking of the note-quality evaluation (SPEC section 11, "Notes")."""

import json
from typing import Any

import pytest

from evals.agents.note_quality import (
    parse_coverage,
    parse_support,
    reference_as_draft,
    support_blocks,
)

pytestmark = pytest.mark.unit


def test_the_reference_note_becomes_sentence_statements_under_its_headings() -> None:
    note = (
        "CHIEF COMPLAINT\n\nCough.\n\nASSESSMENT AND PLAN\n\nStart amoxicillin. Review in 1 week."
    )
    assert [(s["section"], s["text"]) for s in reference_as_draft(note)] == [
        ("chief complaint", "Cough."),
        ("assessment and plan", "Start amoxicillin."),
        ("assessment and plan", "Review in 1 week."),
    ]


def test_each_cited_turn_is_given_once_however_many_statements_cite_it() -> None:
    transcript = ["DOCTOR: Hello.", "PATIENT: I cough at night.", "DOCTOR: Take amoxicillin."]
    statements: list[dict[str, Any]] = [
        {"section": "subjective", "text": "Night cough.", "transcript_turns": [1]},
        {"section": "plan", "text": "Amoxicillin for the cough.", "transcript_turns": [1, 2]},
        {"section": "plan", "text": "Follow up.", "transcript_turns": []},
    ]
    turns, lines = support_blocks(statements, transcript)
    assert turns == "[1] PATIENT: I cough at night.\n[2] DOCTOR: Take amoxicillin."
    assert lines.splitlines() == [
        "1. [subjective] Night cough. (turns: 1)",
        "2. [plan] Amoxicillin for the cough. (turns: 1, 2)",
        "3. [plan] Follow up. (turns: none)",
    ]


def test_coverage_keeps_the_most_important_facts_and_rejects_bad_ratings() -> None:
    facts = [{"fact": f"f{i}", "critical": i == 0, "covered": "yes"} for i in range(5)]
    assert [f["fact"] for f in parse_coverage(json.dumps({"facts": facts}), 3)] == [
        "f0",
        "f1",
        "f2",
    ]
    with pytest.raises(ValueError, match="covered"):
        parse_coverage('{"facts": [{"fact": "x", "critical": true, "covered": "maybe"}]}', 3)
    with pytest.raises(ValueError, match="non-empty"):
        parse_coverage('{"facts": []}', 3)


def test_support_needs_every_statement_rated_exactly_once() -> None:
    ok = '{"statements": [{"n": 2, "support": "partial"}, {"n": 1, "support": "n/a"}]}'
    assert len(parse_support(ok, 2)) == 2
    with pytest.raises(ValueError, match="exactly once"):
        parse_support('{"statements": [{"n": 1, "support": "supported"}]}', 2)
    with pytest.raises(ValueError, match="support must be"):
        parse_support('{"statements": [{"n": 1, "support": "sure"}]}', 1)
