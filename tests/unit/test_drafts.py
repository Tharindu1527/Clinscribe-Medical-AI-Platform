"""Drafts awaiting review survive an API restart and leave only their outcome behind (ADR-0016)."""

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from agents.graph import Agents
from apps.api.auth import Principal, principal
from apps.api.clinical import router
from apps.api.drafts import MemoryDrafts
from tests.unit.test_agent_graph import FakeTools, ScriptedChat
from tests.unit.test_reidentify import NOTE, TRANSCRIPT, FakeAudit, FakeDeid

pytestmark = pytest.mark.unit
APPROVE = {"decision": "approve", "birth_date": "1970-01-01", "family_name": "Ellis"}


def _app(saver: InMemorySaver, drafts: MemoryDrafts, tools: FakeTools) -> TestClient:
    """One API process: its own graph objects over a shared checkpointer and draft store."""
    agents = Agents(ScriptedChat(note=[NOTE]), tools, alias=lambda task: f"alias-{task}")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[principal] = lambda: Principal(user="dr-demo", role="doctor")
    app.state.deid, app.state.audit = FakeDeid(), FakeAudit()
    app.state.checkpointer, app.state.drafts = saver, drafts
    app.state.graph, app.state.ask_graph = agents.build(saver), agents.build()
    return TestClient(app)


@pytest.fixture(autouse=True)
def _approval_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPROVAL_TOKEN_KEY", "a" * 64)


def _config(draft_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": draft_id}}


def _draft(client: TestClient) -> str:
    body = {"encounter_id": "enc-1", "patient_id": "1617", "transcript": TRANSCRIPT}
    response = client.post("/v1/scribe/drafts", json=body)
    assert response.status_code == 200, response.text
    draft_id: str = response.json()["draft_id"]
    return draft_id


def test_a_draft_waits_through_a_restart_and_is_approved_by_the_new_process() -> None:
    saver, drafts, tools = InMemorySaver(), MemoryDrafts(), FakeTools([])
    draft_id = _draft(_app(saver, drafts, tools))
    after_restart = _app(saver, drafts, tools)  # new graph objects, same stores
    waiting: list[dict[str, Any]] = after_restart.get("/v1/drafts").json()
    assert [d["draft_id"] for d in waiting] == [draft_id]
    assert after_restart.get(f"/v1/drafts/{draft_id}").json()["status"] == "awaiting_review"
    result = after_restart.post(f"/v1/drafts/{draft_id}/review", json=APPROVE).json()["result"]
    assert result["status"] == "written"
    assert len(tools.writes) == 1


def test_an_ended_draft_keeps_its_outcome_but_not_its_state() -> None:
    saver, drafts, tools = InMemorySaver(), MemoryDrafts(), FakeTools([])
    client = _app(saver, drafts, tools)
    draft_id = _draft(client)
    client.post(f"/v1/drafts/{draft_id}/review", json=APPROVE)
    assert saver.get_tuple(_config(draft_id)) is None  # the checkpoints are deleted
    assert client.get("/v1/drafts").json() == []
    done = client.get(f"/v1/drafts/{draft_id}").json()
    assert done == {
        "draft_id": draft_id,
        "status": "done",
        "result": {"status": "written", "resource_id": "doc-1"},
    }
    assert client.post(f"/v1/drafts/{draft_id}/review", json=APPROVE).status_code == 409


def test_a_rejected_draft_ends_the_same_way() -> None:
    saver, drafts, tools = InMemorySaver(), MemoryDrafts(), FakeTools([])
    client = _app(saver, drafts, tools)
    draft_id = _draft(client)
    reject = {"decision": "reject", "reason": "wrong patient"}
    assert client.post(f"/v1/drafts/{draft_id}/review", json=reject).status_code == 200
    assert drafts.get(draft_id) is not None
    assert drafts.get(draft_id).status == "rejected"  # type: ignore[union-attr]
    assert saver.get_tuple(_config(draft_id)) is None
    assert tools.writes == []
