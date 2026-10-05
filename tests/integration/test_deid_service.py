"""PROGRESS task 6: the de-ID service replaces PHI and stores no plaintext in Postgres."""

import uuid

import httpx
import psycopg

from config.db import owner_conninfo
from config.settings import Settings

DEID = "http://127.0.0.1:8001"
PHONE = "617-555-0142"
MRN = "00482913"


def _deidentify(encounter: str, text: str) -> dict[str, object]:
    response = httpx.post(
        f"{DEID}/deidentify", json={"encounter_id": encounter, "text": text}, timeout=60
    )
    response.raise_for_status()
    body: dict[str, object] = response.json()
    return body


def test_service_replaces_phi_consistently(stack: list[dict[str, str]]) -> None:
    encounter = f"it-{uuid.uuid4().hex[:12]}"
    first = _deidentify(encounter, f"MRN {MRN}. Call {PHONE}.")
    second = _deidentify(encounter, f"Phone again: {PHONE}.")
    assert first["text"] == "MRN MRN_1. Call PHONE_1."
    assert second["text"] == "Phone again: PHONE_1."
    assert {"entity": "PHONE", "surrogate": "PHONE_1"} in first["replacements"]  # type: ignore[operator]


def test_mapping_rows_hold_no_plaintext(stack: list[dict[str, str]]) -> None:
    encounter = f"it-{uuid.uuid4().hex[:12]}"
    _deidentify(encounter, f"MRN {MRN}. Call {PHONE}.")
    with psycopg.connect(owner_conninfo(Settings())) as conn:
        rows = conn.execute(
            "SELECT encounter_id, lookup_hash, entity_type, surrogate, ciphertext"
            " FROM deid_mappings WHERE encounter_id = %s",
            (encounter,),
        ).fetchall()
    assert len(rows) == 2
    for row in rows:
        stored = b"".join(v if isinstance(v, bytes) else str(v).encode() for v in row)
        assert MRN.encode() not in stored
        assert b"5550142" not in stored.replace(b"-", b"")
