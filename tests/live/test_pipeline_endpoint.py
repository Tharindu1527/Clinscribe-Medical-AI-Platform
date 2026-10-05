"""PROGRESS task 9 gate (plus the task 7 chain check): one real request through the pipeline.

Seeded fake PHI goes in; the answer comes back, the audit row carries the same trace id, and the
trace in Langfuse spans api -> deid -> gateway with none of the seeded values in it.
"""

import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import psycopg

from config.db import app_conninfo
from config.settings import Settings

API = "http://127.0.0.1:8000"
FILE_EXPORT = Path(__file__).resolve().parents[2] / ".artifacts" / "otel" / "traces.jsonl"
SEEDED = {"mrn": "00482913", "phone": "617-555-0142", "name": "Ada Lovelace"}
TEXT = (
    f"Patient {SEEDED['name']}, MRN {SEEDED['mrn']}, called from {SEEDED['phone']} about an "
    "itchy rash on both forearms for 3 days. Summarise the message in one sentence."
)


def _langfuse_observations(trace_id: str, timeout_s: float = 180) -> tuple[list[str], str]:
    settings = Settings()
    auth = (
        settings.langfuse_public_key.get_secret_value(),
        settings.langfuse_secret_key.get_secret_value(),
    )
    now = datetime.now(UTC)
    params = {
        "traceId": trace_id,
        "fromStartTime": (now - timedelta(minutes=30)).isoformat(),
        "toStartTime": (now + timedelta(minutes=5)).isoformat(),
        "limit": "100",
    }
    deadline = time.monotonic() + timeout_s
    names: list[str] = []
    body = ""
    while time.monotonic() < deadline:
        response = httpx.get(
            f"{settings.langfuse_host}/api/public/v2/observations",
            params=params,
            auth=auth,
            timeout=30,
        )
        response.raise_for_status()
        body = response.text
        names = [o["name"] for o in response.json()["data"] if o.get("traceId") == trace_id]
        if {"POST /v1/dev/complete", "POST /deidentify", "chat clinscribe-default"} <= set(names):
            break
        time.sleep(10)
    return names, body


def test_pipeline_answers_audits_and_traces_without_phi() -> None:
    encounter = f"live-{uuid.uuid4().hex[:10]}"
    response = httpx.post(
        f"{API}/v1/dev/complete",
        json={"encounter_id": encounter, "text": TEXT},
        headers={"X-Actor": "live-test"},
        timeout=180,
    )
    assert response.status_code == 200, response.text[:300]
    result = response.json()
    assert result["text"].strip()
    assert result["prompt_version"] == "dev_complete@v1"
    assert result["phi_replaced"].get("MRN") == 1
    assert result["phi_replaced"].get("PHONE") == 1
    trace_id = result["trace_id"]

    with psycopg.connect(app_conninfo(Settings())) as conn:
        row = conn.execute(
            "SELECT trace_id, prompt_version, actor, encounter_id FROM audit_log WHERE seq = %s",
            (result["audit_seq"],),
        ).fetchone()
    assert row == (trace_id, "dev_complete@v1", "live-test", encounter)

    names, body = _langfuse_observations(trace_id)
    assert {"POST /v1/dev/complete", "POST /deidentify", "chat clinscribe-default"} <= set(names), (
        names
    )
    for value in SEEDED.values():
        assert value not in body

    exported = "\n".join(
        line for line in FILE_EXPORT.read_text(encoding="utf-8").splitlines() if trace_id in line
    )
    assert exported
    for value in SEEDED.values():
        assert value not in exported
