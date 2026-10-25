"""LiveKit room tokens for the browser's Voice tab (ADR-0019)."""

import base64
import hashlib
import hmac
import json
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from apps.api.auth import Principal, Role, principal
from apps.api.clinical import router
from apps.api.voice_token import TTL_S, room_token
from tests.unit.test_reidentify import FakeAudit

pytestmark = pytest.mark.unit
KEY, SECRET = SecretStr("APIkey123"), SecretStr("s" * 43)


def _decode(token: str) -> tuple[dict[str, Any], dict[str, Any], bytes, str]:
    def part(text: str) -> bytes:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))

    header, body, signature = token.split(".")
    return json.loads(part(header)), json.loads(part(body)), part(signature), f"{header}.{body}"


def test_the_token_is_an_hs256_jwt_for_one_room() -> None:
    header, claims, signature, signed = _decode(room_token(KEY, SECRET, "dr-demo", "r1", now=1000))
    assert header == {"alg": "HS256", "typ": "JWT"}
    expected = hmac.new(SECRET.get_secret_value().encode(), signed.encode(), hashlib.sha256)
    assert hmac.compare_digest(signature, expected.digest())
    assert claims["iss"] == "APIkey123"
    assert claims["sub"] == "dr-demo"
    assert (claims["nbf"], claims["exp"]) == (1000, 1000 + TTL_S)
    assert claims["video"] == {
        "room": "r1",
        "roomJoin": True,
        "canPublish": True,
        "canSubscribe": True,
        "canPublishData": True,
    }


def test_no_token_without_the_keys() -> None:
    with pytest.raises(RuntimeError, match="gen-keys"):
        room_token(SecretStr(""), SECRET, "dr-demo", "r1")


@pytest.mark.parametrize(("role", "status"), [("doctor", 200), ("admin", 403), ("operator", 403)])
def test_only_doctors_get_a_voice_room_and_each_one_is_audited(
    monkeypatch: pytest.MonkeyPatch, role: str, status: int
) -> None:
    monkeypatch.setenv("LIVEKIT_API_KEY", KEY.get_secret_value())
    monkeypatch.setenv("LIVEKIT_API_SECRET", SECRET.get_secret_value())
    app = FastAPI()
    app.include_router(router)
    who = Principal(user=f"{role}-demo", role=cast(Role, role))
    app.dependency_overrides[principal] = lambda: who
    app.state.audit = FakeAudit()
    response = TestClient(app).post("/v1/voice/token")
    assert response.status_code == status
    if status == 200:
        out = response.json()
        assert out["room"].startswith("clinscribe-doctor-demo-")
        assert _decode(out["token"])[1]["video"]["room"] == out["room"]
        [entry] = app.state.audit.actions("voice.session")
        assert entry.resource_id == out["room"]
