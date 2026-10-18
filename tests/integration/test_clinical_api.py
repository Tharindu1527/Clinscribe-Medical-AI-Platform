"""PROGRESS Phase 3 task 9: role-based access on the clinical endpoints (no model calls).

Needs `just up`; skipped otherwise unless CLINSCRIBE_REQUIRE_STACK=1.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from apps.api.auth import issue_token
from config.settings import Settings

API = "http://127.0.0.1:8000"


def _headers(user: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_token(user, Settings().auth_token_key)}"}


@pytest.fixture(scope="module")
def api(stack: list[dict[str, str]]) -> str:
    return API


def test_no_token_or_a_forged_token_is_refused(api: str) -> None:
    body = {"encounter_id": "e1", "question": "warfarin dose?"}
    assert httpx.post(f"{api}/v1/ask", json=body, timeout=10).status_code == 401
    forged = _headers("dr-demo")["Authorization"][:-4] + "0000"
    response = httpx.post(f"{api}/v1/ask", json=body, headers={"Authorization": forged}, timeout=10)
    assert response.status_code == 401


def test_expired_token_is_refused(api: str) -> None:
    old = issue_token(
        "dr-demo", Settings().auth_token_key, now=datetime.now(UTC) - timedelta(hours=9)
    )
    response = httpx.get(
        f"{api}/v1/drafts/draft-x", headers={"Authorization": f"Bearer {old}"}, timeout=10
    )
    assert response.status_code == 401


@pytest.mark.parametrize("user", ["admin-demo", "ops-demo"])
def test_only_doctors_ask_draft_and_review(api: str, user: str) -> None:
    headers = _headers(user)
    ask = {"encounter_id": "e1", "question": "warfarin dose?"}
    assert httpx.post(f"{api}/v1/ask", json=ask, headers=headers, timeout=10).status_code == 403
    review = {"decision": "approve", "birth_date": "1970-01-01", "family_name": "X"}
    response = httpx.post(f"{api}/v1/drafts/d1/review", json=review, headers=headers, timeout=10)
    assert response.status_code == 403


def test_audit_log_is_for_admin_and_operator_not_doctor(api: str) -> None:
    assert httpx.get(f"{api}/v1/audit", headers=_headers("dr-demo"), timeout=10).status_code == 403
    for user in ("admin-demo", "ops-demo"):
        response = httpx.get(f"{api}/v1/audit?limit=5", headers=_headers(user), timeout=10)
        assert response.status_code == 200
        assert {"actor", "action", "model", "prompt_version"} <= set(response.json()[0])


def test_drafts_awaiting_review_are_listed_for_doctors_only(api: str) -> None:
    response = httpx.get(f"{api}/v1/drafts", headers=_headers("dr-demo"), timeout=10)
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    for user in ("admin-demo", "ops-demo"):
        assert httpx.get(f"{api}/v1/drafts", headers=_headers(user), timeout=10).status_code == 403


def test_review_of_an_unknown_draft_is_404(api: str) -> None:
    review = {"decision": "reject", "reason": "test"}
    response = httpx.post(
        f"{api}/v1/drafts/draft-unknown/review",
        json=review,
        headers=_headers("dr-demo"),
        timeout=10,
    )
    assert response.status_code == 404
