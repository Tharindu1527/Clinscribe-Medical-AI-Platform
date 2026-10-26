"""PROGRESS Phase 5: Lab mode through the API: report PDF -> pending Observations -> confirmation ->
final Observations in HAPI; a report for another patient is refused. The same for an HL7 v2
ORU^R01 message (ADR-0021), which also names the record by MRN. No model calls.

Needs `just up` and `just fhir-load`; skipped otherwise unless CLINSCRIBE_REQUIRE_STACK=1.
"""

import base64
from typing import Any

import httpx
import pytest

from agents.lab.hl7 import build_oru
from agents.lab.pdf import report_lines, write_pdf
from apps.api.auth import issue_token
from config.settings import Settings

API = "http://127.0.0.1:8000"


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_token('dr-demo', Settings().auth_token_key)}"}


@pytest.fixture(scope="module")
def patients(stack: list[dict[str, str]]) -> list[dict[str, Any]]:
    response = httpx.get(
        f"{Settings().fhir_base_url}/Patient",
        params={"_count": "2"},
        timeout=30,
        headers={"Cache-Control": "no-cache"},
    )
    return [e["resource"] for e in response.json()["entry"]]


def _pdf(patient: dict[str, Any]) -> str:
    name = " ".join([*patient["name"][0].get("given", []), patient["name"][0]["family"]])
    rows = [("Glucose", "131", "mg/dL", "70 - 99"), ("Potassium", "4.2", "mmol/L", "3.5 - 5.1")]
    return base64.b64encode(
        write_pdf(report_lines(name, patient["birthDate"], "2026-10-01", rows))
    ).decode()


def test_parse_then_confirm_writes_final_observations(patients: list[dict[str, Any]]) -> None:
    patient = patients[0]
    body = {"patient_id": patient["id"], "pdf_base64": _pdf(patient)}
    parsed = httpx.post(f"{API}/v1/lab/parse", json=body, headers=_headers(), timeout=60)
    assert parsed.status_code == 200, parsed.text
    result = parsed.json()
    assert result["identity"] == {"name": True, "birth_date": True}
    assert result["abnormal"] == ["Glucose 131 mg/dL (H)"]
    assert len(result["observations"]) == 2
    confirm = {"birth_date": patient["birthDate"], "family_name": patient["name"][0]["family"]}
    done = httpx.post(
        f"{API}/v1/lab/{result['lab_id']}/confirm", json=confirm, headers=_headers(), timeout=60
    )
    assert done.status_code == 200, done.text
    written = done.json()["written"]
    assert len(written) == 2
    obs = httpx.get(f"{Settings().fhir_base_url}/Observation/{written[0]}", timeout=30).json()
    assert obs["status"] == "final"
    assert obs["subject"]["reference"] == f"Patient/{patient['id']}"


def test_report_for_another_patient_is_not_written(patients: list[dict[str, Any]]) -> None:
    first, second = patients
    body = {"patient_id": second["id"], "pdf_base64": _pdf(first)}  # first's report, second's chart
    parsed = httpx.post(f"{API}/v1/lab/parse", json=body, headers=_headers(), timeout=60).json()
    assert not all(parsed["identity"].values())
    confirm = {"birth_date": second["birthDate"], "family_name": second["name"][0]["family"]}
    refused = httpx.post(
        f"{API}/v1/lab/{parsed['lab_id']}/confirm", json=confirm, headers=_headers(), timeout=60
    )
    assert refused.status_code == 409


def _oru(patient: dict[str, Any]) -> str:
    mrn = next(
        i["value"]
        for i in patient["identifier"]
        if any(c.get("code") == "MR" for c in i.get("type", {}).get("coding", []))
    )
    return build_oru(
        mrn=mrn,
        family=patient["name"][0]["family"],
        given=patient["name"][0].get("given", []),
        birth_date=patient["birthDate"],
        collected="2026-10-01",
        results=[
            ("2339-0", "Glucose", 131, "mg/dL", "70-99", "H"),
            ("6298-4", "Potassium", 4.2, "mmol/L", "3.5-5.1", "N"),
        ],
    )


def test_an_hl7_message_is_confirmed_into_final_observations(
    patients: list[dict[str, Any]],
) -> None:
    patient = patients[0]
    body = {"patient_id": patient["id"], "hl7_message": _oru(patient)}
    parsed = httpx.post(f"{API}/v1/lab/parse", json=body, headers=_headers(), timeout=60)
    assert parsed.status_code == 200, parsed.text
    result = parsed.json()
    assert result["identity"] == {"name": True, "birth_date": True, "mrn": True}
    assert result["abnormal"] == ["Glucose 131 mg/dL (H)"]
    confirm = {"birth_date": patient["birthDate"], "family_name": patient["name"][0]["family"]}
    done = httpx.post(
        f"{API}/v1/lab/{result['lab_id']}/confirm", json=confirm, headers=_headers(), timeout=60
    )
    assert done.status_code == 200, done.text
    [first, _] = done.json()["written"]
    obs = httpx.get(f"{Settings().fhir_base_url}/Observation/{first}", timeout=30).json()
    assert (obs["status"], obs["code"]["coding"][0]["code"]) == ("final", "2339-0")
    assert obs["subject"]["reference"] == f"Patient/{patient['id']}"


def test_an_hl7_message_for_another_patient_is_not_written(
    patients: list[dict[str, Any]],
) -> None:
    first, second = patients
    body = {"patient_id": second["id"], "hl7_message": _oru(first)}
    parsed = httpx.post(f"{API}/v1/lab/parse", json=body, headers=_headers(), timeout=60).json()
    assert parsed["identity"]["mrn"] is False
    confirm = {"birth_date": second["birthDate"], "family_name": second["name"][0]["family"]}
    refused = httpx.post(
        f"{API}/v1/lab/{parsed['lab_id']}/confirm", json=confirm, headers=_headers(), timeout=60
    )
    assert refused.status_code == 409


def test_a_request_with_both_or_neither_report_is_rejected(patients: list[dict[str, Any]]) -> None:
    patient = patients[0]
    for body in (
        {"patient_id": patient["id"]},
        {"patient_id": patient["id"], "hl7_message": _oru(patient), "pdf_base64": _pdf(patient)},
    ):
        response = httpx.post(f"{API}/v1/lab/parse", json=body, headers=_headers(), timeout=60)
        assert response.status_code == 422
