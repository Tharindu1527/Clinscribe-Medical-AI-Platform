"""Live end-to-end (Phase 3): a doctor asks a cited question, then a consultation becomes a draft,
the doctor approves it and the note is written to FHIR. Real models through the gateway.

Needs `just up` and `just up rag`. Run with `just test-live`.
"""

import base64
from typing import Any

import httpx
import pytest

from apps.api.auth import issue_token
from config.settings import Settings

API = "http://127.0.0.1:8000"
TRANSCRIPT = [
    {"speaker": "doctor", "text": "Good morning, what brings you in today?"},
    {"speaker": "patient", "text": "I have been really thirsty and tired for about three weeks."},
    {"speaker": "doctor", "text": "Your fasting glucose this morning was 9.1 mmol/L."},
    {
        "speaker": "doctor",
        "text": "This fits type 2 diabetes; I would like to confirm with an HbA1c.",
    },
    {"speaker": "doctor", "text": "Let's start metformin 500 mg once daily with the evening meal."},
    {"speaker": "doctor", "text": "We will review you in four weeks with the HbA1c result."},
]


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_token('dr-demo', Settings().auth_token_key)}"}


@pytest.fixture(scope="module")
def patient() -> dict[str, Any]:
    response = httpx.get(
        f"{Settings().fhir_base_url}/Patient",
        params={"_count": "1"},
        timeout=30,
        headers={"Cache-Control": "no-cache"},
    )
    resource: dict[str, Any] = response.json()["entry"][0]["resource"]
    return resource


def test_ask_returns_a_cited_answer() -> None:
    body = {
        "encounter_id": "live-ask-1",
        "question": "What is the usual starting dose of warfarin?",
    }
    response = httpx.post(f"{API}/v1/ask", json=body, headers=_headers(), timeout=300)
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["ai_generated"] is True
    evidence = {e["chunk_id"] for e in out["evidence"]}
    answer = out["answer"]
    if not answer["abstained"]:
        for sentence in answer["sentences"]:
            assert (
                set(sentence["citations"]) <= evidence
            )  # every citation is a passage it was given


def test_scribe_draft_review_and_write(patient: dict[str, Any]) -> None:
    body = {"encounter_id": "live-enc-1", "patient_id": patient["id"], "transcript": TRANSCRIPT}
    response = httpx.post(f"{API}/v1/scribe/drafts", json=body, headers=_headers(), timeout=300)
    assert response.status_code == 200, response.text
    draft = response.json()
    statements = draft["draft"]["statements"]
    assert statements
    assert draft["draft"]["ai_generated"] is True
    assert all(s["transcript_turns"] for s in statements)
    review = {
        "decision": "approve",
        "birth_date": patient["birthDate"],
        "family_name": patient["name"][0]["family"],
    }
    response = httpx.post(
        f"{API}/v1/drafts/{draft['draft_id']}/review", json=review, headers=_headers(), timeout=120
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["status"] == "written", result
    doc = httpx.get(
        f"{Settings().fhir_base_url}/DocumentReference/{result['resource_id']}", timeout=30
    ).json()
    text = base64.b64decode(doc["content"][0]["attachment"]["data"]).decode()
    assert text.startswith("AI-generated draft")
    assert doc["subject"]["reference"] == f"Patient/{patient['id']}"
