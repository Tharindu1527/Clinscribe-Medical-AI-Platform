"""Low-confidence speech on the doctor's review (ADR-0027): the flag rules, the listener's turns,
and the API flow (scripted model, fake de-ID): unsure words reach the review, PHI does not reach the
saved draft."""

import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

import voice.scribe
from agents.graph import Agents
from agents.speech_flags import flag_statements, kept
from apps.api.auth import Principal, principal
from apps.api.clinical import router
from apps.api.drafts import MemoryDrafts
from tests.unit.test_agent_graph import FakeTools, ScriptedChat
from tests.unit.test_reidentify import FakeAudit, FakeDeid
from voice.scribe import Word, group_turns, transcript_for_api, words_from_result

pytestmark = pytest.mark.unit


# ------------------------------------------------------------------ the rules
def test_only_unsure_words_left_after_deid_are_kept_once_each() -> None:
    unsure = [
        {"word": "Ellis", "confidence": 0.31},  # a name de-ID replaced: PHI, dropped
        {"word": "lisinopril", "confidence": 0.62},
        {"word": "Lisinopril", "confidence": 0.41},
        {"word": "daily", "confidence": 0.5},
    ]
    turn = "PERSON_1 takes lisinopril daily."
    assert kept(unsure, turn) == [
        {"word": "Lisinopril", "confidence": 0.41},
        {"word": "daily", "confidence": 0.5},
    ]


def test_function_words_are_not_kept_but_negations_are() -> None:
    unsure = [{"word": w, "confidence": 0.4} for w in ("and", "the", "to", "not", "allergic")]
    words = [u["word"] for u in kept(unsure, "And the rash is not allergic, to be clear.")]
    assert sorted(words) == ["allergic", "not"]


TURNS = [
    "DOCTOR: Which tablets do you take?",
    "PATIENT: Lisinopril every morning.",
    "DOCTOR: I will start high drugs in for the itch.",
]
UNSURE = [[], [{"word": "Lisinopril", "confidence": 0.42}], [{"word": "drugs", "confidence": 0.38}]]


def _statement(text: str, turns: list[int]) -> dict[str, Any]:
    return {"section": "plan", "text": text, "transcript_turns": turns}


def test_a_statement_using_an_unsure_word_is_flagged_heard() -> None:
    [flags] = flag_statements([_statement("Takes lisinopril each morning.", [1])], TURNS, UNSURE)
    assert flags == {
        "heard": [{"word": "Lisinopril", "confidence": 0.42, "turn": 1}],
        "changed": None,
    }


def test_a_drug_its_turns_do_not_say_is_flagged_changed_when_a_turn_was_unsure() -> None:
    """The note writer may have turned what the recogniser heard into a drug name."""
    [flags] = flag_statements([_statement("Start hydroxyzine for the itch.", [2])], TURNS, UNSURE)
    assert flags["heard"] == []
    assert flags["changed"] == {
        "terms": ["hydroxyzine"],
        "unsure": [{"word": "drugs", "confidence": 0.38, "turn": 2}],
    }


@pytest.mark.parametrize(
    ("text", "turns"),
    [
        ("Asked which tablets the patient takes.", [0]),  # its turn has no unsure word
        ("Start hydroxyzine for the itch.", [0]),  # a new drug, but the speech was clear
        ("Lisinopril was not discussed.", [5]),  # a turn index outside the transcript
        ("Plans to treat the itch.", [2]),  # unsure turn, but no word used and no term added
    ],
)
def test_no_flag_without_unsure_speech_behind_the_words(text: str, turns: list[int]) -> None:
    assert flag_statements([_statement(text, turns)], TURNS, UNSURE) == [
        {"heard": [], "changed": None}
    ]


def test_a_word_unsure_in_two_cited_turns_is_shown_once_at_its_lowest_confidence() -> None:
    turns = ["PATIENT: Ramipril.", "PATIENT: Yes, ramipril."]
    unsure = [[{"word": "Ramipril", "confidence": 0.5}], [{"word": "ramipril", "confidence": 0.3}]]
    [flags] = flag_statements([_statement("Takes ramipril.", [0, 1])], turns, unsure)
    assert flags["heard"] == [{"word": "ramipril", "confidence": 0.3, "turn": 1}]


# ------------------------------------------------------------------ the listener
REPORT = Path(__file__).resolve().parents[2] / "evals" / "reports" / "voice" / "asr_confidence.md"


def test_the_listener_uses_the_threshold_the_committed_evaluation_chose() -> None:
    chosen = re.search(r"\| (\d\.\d\d) \*\*\(chosen\)\*\*", REPORT.read_text(encoding="utf-8"))
    assert chosen, "run evals/voice/asr_confidence.py and commit its report"
    assert float(chosen.group(1)) == voice.scribe.UNSURE_BELOW


def test_words_keep_their_confidence_and_turns_list_the_unsure_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(voice.scribe, "UNSURE_BELOW", 0.6)
    data = {
        "type": "Results",
        "is_final": True,
        "channel": {
            "alternatives": [
                {
                    "words": [
                        {"word": "take", "start": 0.0, "end": 0.2, "confidence": 0.99},
                        {
                            "punctuated_word": "lisinopril.",
                            "word": "lisinopril",
                            "start": 0.3,
                            "end": 0.9,
                            "confidence": 0.41,
                        },
                    ]
                }
            ]
        },
    }
    words = words_from_result(data)
    assert [w.confidence for w in words] == [0.99, 0.41]
    [turn] = group_turns(words)
    assert turn.unsure == (("lisinopril", 0.41),)  # punctuation stripped


def test_a_split_turn_sends_each_unsure_word_with_the_part_that_has_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(voice.scribe, "UNSURE_BELOW", 0.6)
    long = "I take ramipril every day. " * 200  # over the API's 4,000 characters per turn
    words = [Word(w, i, i + 0.5, 0) for i, w in enumerate(long.split())]
    words += [Word("Then", 1e4, 1e4, 0), Word("metformin.", 1e4 + 1, 1e4 + 1, 0, confidence=0.3)]
    rows = transcript_for_api(group_turns(words), {0: "patient"})
    assert len(rows) > 1
    assert [r.get("unsure", []) for r in rows] == [[]] * (len(rows) - 1) + [
        [{"word": "metformin", "confidence": 0.3}]
    ]


# ------------------------------------------------------------------ the API
NOTE = {
    "statements": [
        {"section": "subjective", "text": "Takes lisinopril every morning.", "turns": [1]},
        {"section": "plan", "text": "Start hydroxyzine for the itch.", "turns": [2]},
    ]
}
TRANSCRIPT = [
    {"speaker": "doctor", "text": "Which tablets do you take?"},
    {
        "speaker": "patient",
        "text": "I am Morgan Ellis. Lisinopril every morning.",
        "unsure": [
            {"word": "Ellis", "confidence": 0.31},
            {"word": "Lisinopril", "confidence": 0.42},
        ],
    },
    {
        "speaker": "doctor",
        "text": "I will start high drugs in for the itch.",
        "unsure": [{"word": "drugs", "confidence": 0.38}],
    },
]


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, FastAPI]:
    monkeypatch.setenv("APPROVAL_TOKEN_KEY", "a" * 64)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[principal] = lambda: Principal(user="dr-demo", role="doctor")
    app.state.deid = FakeDeid()
    app.state.audit = FakeAudit()
    agents = Agents(ScriptedChat(note=[NOTE] * 3), FakeTools([]), alias=lambda task: f"a-{task}")
    app.state.checkpointer = InMemorySaver()
    app.state.graph = agents.build(app.state.checkpointer)
    app.state.drafts = MemoryDrafts()
    return TestClient(app), app


def test_the_review_shows_unsure_speech_and_the_saved_draft_holds_no_phi(
    api: tuple[TestClient, FastAPI],
) -> None:
    client, app = api
    body = {"encounter_id": "enc-1", "patient_id": "1617", "transcript": TRANSCRIPT}
    response = client.post("/v1/scribe/drafts", json=body)
    assert response.status_code == 200, response.text
    speech = response.json()["unsure_speech"]
    assert speech["turns"] == [
        [],
        [{"word": "Lisinopril", "confidence": 0.42}],
        [{"word": "drugs", "confidence": 0.38}],
    ]
    heard, changed = speech["statements"]
    assert [u["word"] for u in heard["heard"]] == ["Lisinopril"]
    assert changed["changed"]["terms"] == ["hydroxyzine"]

    draft_id = response.json()["draft_id"]
    saved = app.state.graph.get_state({"configurable": {"thread_id": draft_id}}).values
    dumped = json.dumps(saved, default=str)
    assert "Ellis" not in dumped
    assert "Morgan" not in dumped
    [entry] = app.state.audit.actions("draft.create")
    assert (entry.details["unsure_words"], entry.details["statements_unsure"]) == (2, 2)
    assert client.get(f"/v1/drafts/{draft_id}").json()["unsure_speech"] == speech


@pytest.mark.parametrize(
    "unsure",
    [
        [{"word": "two words", "confidence": 0.4}],
        [{"word": "lisinopril", "confidence": 1.5}],
        [{"word": "x", "confidence": 0.1}] * 201,
    ],
)
def test_malformed_unsure_words_are_refused(
    api: tuple[TestClient, FastAPI], unsure: list[dict[str, Any]]
) -> None:
    client, _ = api
    turn = {"speaker": "patient", "text": "Lisinopril.", "unsure": unsure}
    body = {"encounter_id": "enc-1", "patient_id": "1617", "transcript": [turn]}
    assert client.post("/v1/scribe/drafts", json=body).status_code == 422
