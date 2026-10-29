"""Prompt building and reply checking of the note-quality evaluation (SPEC section 11, "Notes")."""

import json
from typing import Any

import pytest

from evals.agents.note_eval import turns
from evals.agents.note_quality import (
    Recording,
    parse_coverage,
    parse_support,
    reference_as_draft,
    support_blocks,
    writer_replies,
)
from llmops.gateway.client import Completion

pytestmark = pytest.mark.unit


def test_a_line_without_a_speaker_tag_continues_the_turn_above() -> None:
    # ACI-Bench D2N072: the doctor's assessment and plan follow a dictation command on their own
    # line; dropping it (as before 2026-10-29) left the note writer a consultation without a plan
    dialogue = (
        "[doctor] all right . so , on this x-ray.\n"
        "everything looks normal . we'll give you 600 milligrams every six hours .\n"
        "[patient] okay .\n"
        "[patient_guest]\n"
        "\n"
        "[doctor_guest] any questions ?"
    )
    assert turns(dialogue) == [
        (
            "doctor",
            "all right . so , on this x-ray. everything looks normal . "
            "we'll give you 600 milligrams every six hours .",
        ),
        ("patient", "okay ."),
        ("doctor", "any questions ?"),
    ]


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


def _reply(finish: str, thinking: int) -> Completion:
    return Completion("{}", "m", 2000, thinking + 900, 30_000.0, finish_reason=finish,
                      reasoning_tokens=thinking)  # fmt: skip


def _result(finish: str, recall: float, critical: float, unsupported: int) -> dict[str, Any]:
    scores = {"recall": recall, "critical_recall": critical, "unsupported": unsupported}
    return {"id": "aci-x", "draft": True, "statements": 50, "calls": [_reply(finish, 1000)],
            "draft_scores": scores}  # fmt: skip


def _verdict(results: list[dict[str, Any]]) -> list[str]:
    judged = [r for r in results if r["draft"]]
    lines = writer_replies(results, [r["draft_scores"] for r in judged], judged)
    return [line for line in lines if line.startswith("- ")]


def test_adr_0030_rule_adopts_only_when_every_check_passes() -> None:
    # ADR-0030: complete (no "length" reply), recall >= 0.80, critical >= 0.87, unsupported <= 3%
    good = [_result("stop", 0.85, 0.90, 1), _result("stop", 0.80, 0.88, 2)]
    assert _verdict(good)[-1].startswith("- **adopt**")
    for bad in (
        [_result("length", 0.85, 0.90, 1), *good],  # a reply cut off
        [_result("stop", 0.70, 0.90, 1), good[0]],  # recall 0.775
        [_result("stop", 0.85, 0.80, 1), good[0]],  # critical recall 0.85
        [_result("stop", 0.85, 0.90, 3), good[0]],  # 4 of 100 statements unsupported
        [{"id": "aci-y", "draft": False, "calls": [_reply("stop", 900)]}, *good],  # no draft
    ):
        assert _verdict(bad)[-1].startswith("- **do not adopt**"), bad


def test_recording_keeps_only_the_note_writers_replies() -> None:
    class Fake:
        def complete(self, model: str, messages: Any, **kwargs: Any) -> Completion:
            return _reply("stop", 10)

    recording = Recording(Fake(), "clinscribe-eval-gemini-2.5-flash")  # type: ignore[arg-type]
    recording.complete("clinscribe-judge", [])
    recording.complete("clinscribe-eval-gemini-2.5-flash", [])
    assert len(recording.calls) == 1
