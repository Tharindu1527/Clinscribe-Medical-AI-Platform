"""Live end-to-end (Phase 3): a doctor asks a cited question, then a consultation becomes a draft,
the doctor approves it and the note is written to FHIR. Real models through the gateway.

Needs `just up` and `just up rag`. Run with `just test-live`.
"""

import base64
import subprocess
import time
from typing import Any

import httpx
import pytest

from apps.api.auth import issue_token
from apps.api.edits import PostgresEditPairs
from config.db import app_conninfo
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


def test_the_doctor_reads_and_the_record_holds_the_originals(patient: dict[str, Any]) -> None:
    """ADR-0015: the model sees surrogates; the doctor's view and the approved record do not."""
    name = "Dana Whitfield"  # synthetic
    transcript = [{"speaker": "patient", "text": f"My name is {name}."}, *TRANSCRIPT[1:]]
    body = {"encounter_id": "live-enc-reid", "patient_id": patient["id"], "transcript": transcript}
    response = httpx.post(
        f"{API}/v1/scribe/drafts?identified=true", json=body, headers=_headers(), timeout=300
    )
    assert response.status_code == 200, response.text
    draft = response.json()
    assert name not in draft["transcript"][0]  # what the model saw
    assert name in draft["identified"]["transcript"][0]  # what the doctor reads
    note = draft["draft"]
    note["statements"][0]["text"] = f"{name} reports thirst and tiredness for three weeks."
    review = {
        "decision": "edit",
        "edited": note,
        "edited_identified": True,
        "birth_date": patient["birthDate"],
        "family_name": patient["name"][0]["family"],
    }
    response = httpx.post(
        f"{API}/v1/drafts/{draft['draft_id']}/review", json=review, headers=_headers(), timeout=120
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["status"] == "written", result
    assert name not in str(result["edit_pair"])  # future evaluation data stays de-identified
    [kept] = [
        p
        for p in PostgresEditPairs(app_conninfo(Settings())).all()
        if p.draft_id == draft["draft_id"]
    ]
    assert "three weeks" in str(kept.after)  # the doctor's edit, kept for evaluation (ADR-0028)
    assert name not in str(kept.before) + str(kept.after)
    doc = httpx.get(
        f"{Settings().fhir_base_url}/DocumentReference/{result['resource_id']}", timeout=30
    ).json()
    assert name in base64.b64decode(doc["content"][0]["attachment"]["data"]).decode()


def _wait_for_api(timeout_s: float = 180) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{API}/health", timeout=5).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise TimeoutError("the API did not come back")


def test_a_pending_draft_survives_an_api_restart(patient: dict[str, Any]) -> None:
    """ADR-0016: drafts awaiting review are checkpointed in Postgres, not in the API's memory."""
    body = {
        "encounter_id": "live-enc-restart",
        "patient_id": patient["id"],
        "transcript": TRANSCRIPT,
    }
    response = httpx.post(f"{API}/v1/scribe/drafts", json=body, headers=_headers(), timeout=300)
    assert response.status_code == 200, response.text
    draft_id = response.json()["draft_id"]
    subprocess.run(["docker", "compose", "restart", "api"], check=True, timeout=180)
    _wait_for_api()
    waiting = httpx.get(f"{API}/v1/drafts", headers=_headers(), timeout=30).json()
    assert draft_id in [d["draft_id"] for d in waiting]
    review = {
        "decision": "approve",
        "birth_date": patient["birthDate"],
        "family_name": patient["name"][0]["family"],
    }
    response = httpx.post(
        f"{API}/v1/drafts/{draft_id}/review", json=review, headers=_headers(), timeout=120
    )
    assert response.json()["result"]["status"] == "written", response.text
    done = httpx.get(f"{API}/v1/drafts/{draft_id}", headers=_headers(), timeout=30).json()
    assert done["status"] == "done"
    assert done["result"]["status"] == "written"


def test_a_question_about_a_drug_no_source_covers_abstains_without_a_model() -> None:
    """ADR-0018: the corpus never names mazdutide, so no answer can be about it."""
    body = {
        "encounter_id": "live-ask-unseen",
        "question": "Which side effects does mazdutide cause?",
    }
    response = httpx.post(f"{API}/v1/ask", json=body, headers=_headers(), timeout=120)
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["answer"]["abstained"] is True
    assert out["unseen_terms"] == ["mazdutide"]
    assert out["answer"]["model"] == "none"  # ended before search and generation
    assert out["evidence"] == []
