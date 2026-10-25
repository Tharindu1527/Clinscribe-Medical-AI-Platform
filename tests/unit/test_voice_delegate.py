"""The voice agent asks as the doctor in its room, never as anyone else (ADR-0019)."""

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from apps.api.auth import read_token
from apps.api.clinical import router
from tests.unit.test_reidentify import FakeAudit

pytestmark = pytest.mark.unit
AGENT_KEY, AUTH_KEY = "v" * 64, "k" * 64
ROOM = "clinscribe-dr-second-0a1b2c3d"


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setenv("VOICE_AGENT_KEY", AGENT_KEY)
    monkeypatch.setenv("AUTH_TOKEN_KEY", AUTH_KEY)
    app = FastAPI()
    app.include_router(router)
    app.state.audit = FakeAudit()
    return app


def _ask(
    app: FastAPI, room: str = ROOM, user: str = "dr-second", key: str | None = AGENT_KEY
) -> Any:  # Starlette's TestClient response
    headers = {} if key is None else {"X-Voice-Agent-Key": key}
    return TestClient(app).post(
        "/v1/voice/delegate", json={"room": room, "user": user}, headers=headers
    )


def test_the_agent_gets_a_short_token_for_the_doctor_and_it_is_audited(app: FastAPI) -> None:
    response = _ask(app)
    assert response.status_code == 200
    who = read_token(response.json()["token"], SecretStr(AUTH_KEY))
    assert (who.user, who.role) == ("dr-second", "doctor")
    [entry] = app.state.audit.actions("voice.delegate")
    assert (entry.actor, entry.resource_id) == ("dr-second", ROOM)


@pytest.mark.parametrize("key", [None, "", "v" * 63 + "w"])
def test_only_the_voice_agent_may_ask(app: FastAPI, key: str | None) -> None:
    assert _ask(app, key=key).status_code == 403
    assert app.state.audit.entries == []


def test_nothing_is_delegated_when_the_service_has_no_key(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VOICE_AGENT_KEY", "")
    assert _ask(app, key="").status_code == 403


@pytest.mark.parametrize(
    ("room", "user"),
    [
        (ROOM, "dr-demo"),  # another doctor's room
        ("clinscribe-admin-demo-0a1b2c3d", "admin-demo"),  # not a doctor
        ("clinscribe-dr-nobody-0a1b2c3d", "dr-nobody"),  # not a user
    ],
)
def test_only_the_doctor_the_room_was_issued_to(app: FastAPI, room: str, user: str) -> None:
    assert _ask(app, room=room, user=user).status_code == 403
    assert app.state.audit.entries == []


@pytest.mark.parametrize("room", ["dr-second", "clinscribe-dr-second-XYZ", "clinscribe-dr-second"])
def test_a_room_name_the_api_never_issues_is_rejected(app: FastAPI, room: str) -> None:
    assert _ask(app, room=room).status_code == 422
