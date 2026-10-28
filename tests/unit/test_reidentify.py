"""Re-identification for the doctor's screen and the approved record (ADR-0015): the de-ID route
only the API can call, the client, and the API's review flow (scripted model, fake tools)."""

import base64
import json
from typing import Any, cast

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from presidio_analyzer import AnalyzerEngine
from pydantic import SecretStr

from agents.approval import verify
from agents.graph import Agents
from apps.api.auth import Principal, principal
from apps.api.clinical import router
from apps.api.drafts import MemoryDrafts
from apps.api.edits import MemoryEditPairs
from privacy.deid.app import app as deid_app
from privacy.deid.client import DeidClient, DeidOutput, Reidentified
from privacy.deid.engine import Deidentifier
from privacy.deid.store import InMemoryStore
from privacy.deid.types import issue
from tests.unit.test_agent_graph import FakeTools, ScriptedChat

pytestmark = pytest.mark.unit
KEY = "r" * 64


# ------------------------------------------------------------------ the de-ID service route
@pytest.fixture
def deid_service(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, str]:
    store = InMemoryStore(SecretStr(Fernet.generate_key().decode()))
    surrogate = store.surrogate_for("enc-r", "PERSON", "Morgan Ellis")
    deidentifier = Deidentifier(cast(AnalyzerEngine, None), store)  # re-identify needs no analyzer
    monkeypatch.setattr(deid_app.state, "deidentifier", deidentifier, raising=False)
    monkeypatch.setattr(deid_app.state, "reidentify_key", KEY, raising=False)
    return TestClient(deid_app), surrogate


def test_the_route_restores_originals_for_the_key_holder(
    deid_service: tuple[TestClient, str],
) -> None:
    client, surrogate = deid_service
    body = {"encounter_id": "enc-r", "texts": [f"{surrogate} reports thirst.", "PERSON_9 left."]}
    response = client.post("/reidentify", json=body, headers={"X-Reidentify-Key": KEY})
    assert response.status_code == 200
    # an unknown surrogate (another encounter's, or none) stays as it is
    assert response.json() == {
        "texts": ["Morgan Ellis reports thirst.", "PERSON_9 left."],
        "restored": 1,
    }


@pytest.mark.parametrize("headers", [{}, {"X-Reidentify-Key": "wrong"}])
def test_the_route_refuses_without_the_key(
    deid_service: tuple[TestClient, str], headers: dict[str, str]
) -> None:
    client, surrogate = deid_service
    body = {"encounter_id": "enc-r", "texts": [surrogate]}
    assert client.post("/reidentify", json=body, headers=headers).status_code == 403


def test_the_route_is_closed_when_the_service_has_no_key(
    deid_service: tuple[TestClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, surrogate = deid_service
    monkeypatch.setattr(deid_app.state, "reidentify_key", "")
    body = {"encounter_id": "enc-r", "texts": [surrogate]}
    assert (
        client.post("/reidentify", json=body, headers={"X-Reidentify-Key": ""}).status_code == 403
    )


def test_the_client_sends_the_key_and_a_client_without_one_cannot_reidentify() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"texts": ["Morgan Ellis"], "restored": 1})

    transport = httpx.MockTransport(handler)
    out = DeidClient("http://deid", transport=transport, reidentify_key=KEY).reidentify(
        ["PERSON_1"], "enc-r"
    )
    assert out == Reidentified(texts=["Morgan Ellis"], restored=1)
    assert seen[0].headers["X-Reidentify-Key"] == KEY
    with pytest.raises(RuntimeError, match="no re-identification key"):
        DeidClient("http://deid", transport=transport).reidentify(["PERSON_1"], "enc-r")
    assert len(seen) == 1


# ------------------------------------------------------------------ the API's review flow
ORIGINALS = {"Morgan Ellis": "PERSON_1", "Denver": "LOCATION_1"}
TRANSCRIPT = [
    {"speaker": "doctor", "text": "What brings you in?"},
    {"speaker": "patient", "text": "I am Morgan Ellis, back from Denver, and always thirsty."},
]
NOTE = {
    "statements": [
        {
            "section": "subjective",
            "text": "PERSON_1 has been thirsty since LOCATION_1.",
            "turns": [1],
        }
    ]
}


class FakeDeid:
    """Replaces the known originals with their surrogates and back."""

    def deidentify(self, text: str, encounter_id: str) -> DeidOutput:
        for original, surrogate in ORIGINALS.items():
            text = text.replace(original, surrogate)
        return DeidOutput(issue(text, source="synthetic-test-fixture"), {})

    def reidentify(self, texts: list[str], encounter_id: str) -> Reidentified:
        out, restored = [], 0
        for text in texts:
            for original, surrogate in ORIGINALS.items():
                restored += text.count(surrogate)
                text = text.replace(surrogate, original)
            out.append(text)
        return Reidentified(out, restored)


class FakeAudit:
    def __init__(self) -> None:
        self.entries: list[Any] = []

    def append(self, entry: Any) -> int:
        self.entries.append(entry)
        return len(self.entries)

    def actions(self, action: str) -> list[Any]:
        return [e for e in self.entries if e.action == action]


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, FakeTools, FakeAudit]:
    monkeypatch.setenv("APPROVAL_TOKEN_KEY", "a" * 64)
    tools = FakeTools([])
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[principal] = lambda: Principal(user="dr-demo", role="doctor")
    app.state.deid = FakeDeid()
    app.state.audit = FakeAudit()
    agents = Agents(ScriptedChat(note=[NOTE] * 3), tools, alias=lambda task: f"alias-{task}")
    app.state.checkpointer = InMemorySaver()
    app.state.graph = agents.build(app.state.checkpointer)
    app.state.ask_graph = agents.build()
    app.state.drafts = MemoryDrafts()
    app.state.edits = MemoryEditPairs()
    return TestClient(app), tools, app.state.audit


def _draft(client: TestClient, identified: bool) -> dict[str, Any]:
    body = {"encounter_id": "enc-1", "patient_id": "1617", "transcript": TRANSCRIPT}
    url = "/v1/scribe/drafts" + ("?identified=true" if identified else "")
    response = client.post(url, json=body)
    assert response.status_code == 200, response.text
    out: dict[str, Any] = response.json()
    return out


def _written_text(tools: FakeTools) -> str:
    data = tools.writes[0].resource["content"][0]["attachment"]["data"]
    return base64.b64decode(data).decode()


def test_the_doctor_sees_originals_only_on_request_and_each_disclosure_is_audited(
    api: tuple[TestClient, FakeTools, FakeAudit],
) -> None:
    client, _, audit = api
    plain = _draft(client, identified=False)
    assert "identified" not in plain
    assert "PERSON_1" in plain["draft"]["statements"][0]["text"]
    assert audit.actions("phi.reidentify") == []

    shown = _draft(client, identified=True)
    assert shown["identified"]["statements"] == ["Morgan Ellis has been thirsty since Denver."]
    assert "Morgan Ellis" in shown["identified"]["transcript"][1]
    assert "PERSON_1" in shown["draft"]["statements"][0]["text"]  # the model's view is kept
    [entry] = audit.actions("phi.reidentify")
    assert entry.details == {"context": "draft", "texts": 3, "restored": 4}
    assert "Morgan" not in json.dumps(entry.details)

    again = client.get(f"/v1/drafts/{shown['draft_id']}?identified=true").json()
    assert again["identified"] == shown["identified"]


def test_approval_writes_and_signs_the_note_as_the_doctor_read_it(
    api: tuple[TestClient, FakeTools, FakeAudit],
) -> None:
    client, tools, audit = api
    draft = _draft(client, identified=True)
    review = {"decision": "approve", "birth_date": "1970-01-01", "family_name": "Ellis"}
    response = client.post(f"/v1/drafts/{draft['draft_id']}/review", json=review)
    assert response.json()["result"]["status"] == "written"
    written = _written_text(tools)
    assert "Morgan Ellis has been thirsty since Denver." in written
    assert "PERSON_1" not in written
    # the token covers exactly the resource that was written
    verify(tools.writes[0].approval, SecretStr("a" * 64), content=tools.writes[0].resource)
    assert [e.details["context"] for e in audit.actions("phi.reidentify")] == ["draft", "record"]


def test_edits_on_the_identified_view_go_to_the_record_and_back_to_surrogates_for_the_graph(
    api: tuple[TestClient, FakeTools, FakeAudit],
) -> None:
    client, tools, _ = api
    draft = _draft(client, identified=True)
    note = draft["draft"]
    note["statements"][0]["text"] = "Morgan Ellis has been thirsty for three weeks since Denver."
    review = {
        "decision": "edit",
        "edited": note,
        "edited_identified": True,
        "birth_date": "1970-01-01",
        "family_name": "Ellis",
    }
    result = client.post(f"/v1/drafts/{draft['draft_id']}/review", json=review).json()["result"]
    assert "Morgan Ellis has been thirsty for three weeks since Denver." in _written_text(tools)
    after = result["edit_pair"]["after"]["statements"][0]["text"]
    assert after == "PERSON_1 has been thirsty for three weeks since LOCATION_1."
