from pathlib import Path

import httpx
import pytest

from scripts.fhir_load import (
    SYNTHEA_ID_SYSTEM,
    bundle_order,
    sha256_of,
    synthea_patient_id,
    wait_for_fhir,
)


def test_wait_for_fhir_retries_until_the_server_answers() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if len(calls) == 1:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        if len(calls) == 2:
            return httpx.Response(503)
        return httpx.Response(200, json={"resourceType": "CapabilityStatement"})

    client = httpx.Client(base_url="http://fhir/fhir/", transport=httpx.MockTransport(handler))
    wait_for_fhir(client, timeout_s=5, interval_s=0)
    assert calls == ["/fhir/metadata"] * 3


def test_wait_for_fhir_gives_up_with_the_last_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = httpx.Client(base_url="http://fhir/fhir/", transport=httpx.MockTransport(handler))
    with pytest.raises(SystemExit, match="HTTP 503"):
        wait_for_fhir(client, timeout_s=0.05, interval_s=0.01)


def test_bundles_load_organisations_then_practitioners_then_patients() -> None:
    names = [
        "Zoe_Smith_1.json",
        "practitionerInformation123.json",
        "Adam_Jones_2.json",
        "hospitalInformation456.json",
    ]
    ordered = [p.name for p in bundle_order([Path(n) for n in names])]
    assert ordered == [
        "hospitalInformation456.json",
        "practitionerInformation123.json",
        "Adam_Jones_2.json",
        "Zoe_Smith_1.json",
    ]


def test_synthea_patient_id_found_only_in_patient_bundles() -> None:
    patient_bundle = {
        "entry": [
            {"resource": {"resourceType": "Encounter"}},
            {
                "resource": {
                    "resourceType": "Patient",
                    "identifier": [
                        {"system": "http://hospital.example/mrn", "value": "MRN-1"},
                        {"system": SYNTHEA_ID_SYSTEM, "value": "abc-123"},
                    ],
                }
            },
        ]
    }
    org_bundle = {"entry": [{"resource": {"resourceType": "Organization"}}]}
    assert synthea_patient_id(patient_bundle) == "abc-123"
    assert synthea_patient_id(org_bundle) is None


def test_sha256_of(tmp_path: Path) -> None:
    sample = tmp_path / "x.bin"
    sample.write_bytes(b"abc")  # FIPS 180-2 test vector
    assert sha256_of(sample) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
