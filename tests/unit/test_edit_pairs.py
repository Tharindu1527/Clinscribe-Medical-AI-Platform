"""Doctors' edits kept as evaluation data (ADR-0028): what changed per statement, the PHI scan
before export, and the API keeping pairs in surrogate form (scripted model, fake de-ID)."""

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from agents.graph import Agents
from apps.api.auth import Principal, principal
from apps.api.clinical import router
from apps.api.drafts import MemoryDrafts
from apps.api.edits import EditPair, MemoryEditPairs
from config.settings import Settings
from evals.agents.edit_pairs import changes, export
from evals.privacy.deid_eval import deidentifier_for
from privacy.deid.client import DeidOutput
from privacy.deid.types import issue
from tests.unit.test_agent_graph import FakeTools, ScriptedChat
from tests.unit.test_reidentify import NOTE, TRANSCRIPT, FakeAudit, FakeDeid

pytestmark = pytest.mark.unit


def _s(section: str, text: str) -> dict[str, Any]:
    return {"section": section, "text": text, "transcript_turns": [1], "citations": []}


# ------------------------------------------------------------------ what changed
def test_statements_are_counted_unchanged_edited_removed_and_added() -> None:
    before = [_s("subjective", "Thirsty."), _s("plan", "Start metformin."), _s("plan", "Review.")]
    after = [_s("subjective", "Thirsty."), _s("plan", "Start metformin 500 mg."), _s("plan", "X")]
    counted = changes(before, after)
    assert {k: counted[k] for k in ("unchanged", "edited", "removed", "added")} == {
        "unchanged": 1,
        "edited": 2,
        "removed": 0,
        "added": 0,
    }
    assert counted["edited:plan"] == 2
    shorter = changes(before, before[:1] + [_s("assessment", "Likely dehydration.")] + before[1:2])
    assert (shorter["unchanged"], shorter["added"], shorter["removed"]) == (2, 1, 1)


# ------------------------------------------------------------------ the PHI scan
def _pair(text_after: str) -> EditPair:
    note = {"statements": [_s("subjective", "PERSON_1 has been thirsty.")]}
    return EditPair(
        "d", "dr-demo", "note_writer@v2", "m", note, {"statements": [_s("subjective", text_after)]}
    )


class _FlagsMorgan:
    def deidentify(self, text: str, encounter_id: str) -> SimpleNamespace:
        return SimpleNamespace(replacements=["x"] if "Morgan" in text else [])


def test_a_pair_the_scan_finds_phi_in_is_withheld() -> None:
    rows, summary = export(
        [_pair("PERSON_1 is thirsty."), _pair("Morgan is thirsty.")], _FlagsMorgan()
    )
    assert (summary["pairs"], summary["withheld_phi"], summary["exported"]) == (2, 1, 1)
    assert rows[0]["after"][0]["text"] == "PERSON_1 is thirsty."
    assert "reviewer" not in rows[0]  # evaluation data needs no user ids


def test_the_real_engine_withholds_a_typed_name_but_not_a_surrogate() -> None:
    engine = deidentifier_for("spacy", Settings.model_fields["deid_spacy_model"].default)
    surrogates = _pair("PERSON_1 has been thirsty for three weeks.")
    _, summary = export([surrogates, _pair("Jane Smith reports chest pain.")], engine)
    assert (summary["exported"], summary["withheld_phi"]) == (1, 1)


# ------------------------------------------------------------------ the API
NOTE_TWO = {
    "statements": [
        *NOTE["statements"],
        {"section": "subjective", "text": "Patient reports thirst.", "turns": [1]},
    ]
}


class _OverRedacts(FakeDeid):
    """Also takes "Patient" for a name, as the fine-tuned tagger did on a real edit."""

    def deidentify(self, text: str, encounter_id: str) -> DeidOutput:
        out = super().deidentify(text, encounter_id).text.text.replace("Patient", "PERSON_9")
        return DeidOutput(issue(out, source="synthetic-test-fixture"), {})


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, FastAPI]:
    monkeypatch.setenv("APPROVAL_TOKEN_KEY", "a" * 64)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[principal] = lambda: Principal(user="dr-demo", role="doctor")
    app.state.deid = _OverRedacts()
    app.state.audit = FakeAudit()
    agents = Agents(ScriptedChat(note=[NOTE_TWO] * 3), FakeTools([]), alias=lambda t: f"a-{t}")
    app.state.checkpointer = InMemorySaver()
    app.state.graph = agents.build(app.state.checkpointer)
    app.state.drafts = MemoryDrafts()
    app.state.edits = MemoryEditPairs()
    return TestClient(app), app


IDENTIFIERS = {"birth_date": "1970-01-01", "family_name": "Ellis"}


def _draft(client: TestClient) -> dict[str, Any]:
    body = {"encounter_id": "enc-1", "patient_id": "1617", "transcript": TRANSCRIPT}
    out: dict[str, Any] = client.post("/v1/scribe/drafts", json=body).json()
    return out


def test_an_edit_typed_on_the_ais_view_reaches_the_pair_in_surrogate_form(
    api: tuple[TestClient, FastAPI],
) -> None:
    """A name typed where the note shows surrogates is de-identified before the graph keeps it."""
    client, app = api
    draft = _draft(client)  # the surrogate view (no ?identified=true)
    note = draft["draft"]
    note["statements"][0]["text"] = "PERSON_1, Morgan Ellis, has been thirsty for three weeks."
    review = {"decision": "edit", "edited": note, **IDENTIFIERS}
    result = client.post(f"/v1/drafts/{draft['draft_id']}/review", json=review).json()["result"]
    assert result["status"] == "written"
    [pair] = app.state.edits.all()
    assert pair.after["statements"][0]["text"] == (
        "PERSON_1, PERSON_1, has been thirsty for three weeks."
    )
    assert "Morgan" not in str(pair.before) + str(pair.after)
    assert pair.before["statements"][0]["text"] == "PERSON_1 has been thirsty since LOCATION_1."
    assert (pair.reviewer, pair.prompt_version) == ("dr-demo", note["prompt_version"])
    [entry] = app.state.audit.actions("draft.edit")
    assert entry.details["edit_pair_kept"] is True


def test_statements_left_as_shown_keep_the_models_text(api: tuple[TestClient, FastAPI]) -> None:
    """Only what the doctor changed goes through de-ID again, on either view."""
    client, app = api
    body = {"encounter_id": "enc-1", "patient_id": "1617", "transcript": TRANSCRIPT}
    draft = client.post("/v1/scribe/drafts?identified=true", json=body).json()
    note = draft["draft"]
    shown = draft["identified"]["statements"]
    note["statements"] = [
        {**s, "text": t} for s, t in zip(note["statements"], shown, strict=True)
    ]  # the doctor's view: originals
    note["statements"][0]["text"] = "Morgan Ellis has been thirsty for three weeks."
    review = {"decision": "edit", "edited": note, "edited_identified": True, **IDENTIFIERS}
    client.post(f"/v1/drafts/{draft['draft_id']}/review", json=review).raise_for_status()
    [pair] = app.state.edits.all()
    assert [s["text"] for s in pair.after["statements"]] == [
        "PERSON_1 has been thirsty for three weeks.",
        "Patient reports thirst.",  # untouched: not "PERSON_9 reports thirst."
    ]
    counted = changes(pair.before["statements"], pair.after["statements"])
    assert (counted["edited"], counted["unchanged"]) == (1, 1)
    contexts = [e.details["context"] for e in app.state.audit.actions("phi.reidentify")]
    assert contexts == ["draft", "review"]  # the comparison restores originals: audited


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_no_pair_without_an_edit(api: tuple[TestClient, FastAPI], decision: str) -> None:
    client, app = api
    draft = _draft(client)
    review = {"decision": decision, **IDENTIFIERS, "reason": "not needed"}
    client.post(f"/v1/drafts/{draft['draft_id']}/review", json=review).raise_for_status()
    assert app.state.edits.all() == []
