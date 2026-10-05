"""PROGRESS task 4 gate (Phase 1 gate c): Synthea patients are queryable from FHIR."""

import os
from collections.abc import Iterator

import httpx
import pytest

from config.settings import Settings
from scripts.fhir_load import load

FHIR = "http://127.0.0.1:8080/fhir/"


@pytest.fixture(scope="module")
def fhir(stack: list[dict[str, str]]) -> Iterator[httpx.Client]:
    # no-cache: counts must reflect what is stored now, not HAPI's ~60 s search cache
    with httpx.Client(base_url=FHIR, timeout=120, headers={"Cache-Control": "no-cache"}) as client:
        total = client.get("Patient", params={"_summary": "count"}).json().get("total", 0)
        if total == 0:
            if os.environ.get("CLINSCRIBE_REQUIRE_STACK") == "1":
                pytest.fail("no patients loaded (just fhir-load)")
            pytest.skip("no patients loaded (just fhir-load)")
        yield client


def _count(client: httpx.Client, resource: str, **params: str) -> int:
    response = client.get(resource, params={**params, "_summary": "count"})
    response.raise_for_status()
    return int(response.json()["total"])


def test_patient_count_matches_population(fhir: httpx.Client) -> None:
    assert _count(fhir, "Patient") == Settings().synthea_population


def test_every_patient_has_an_encounter(fhir: httpx.Client) -> None:
    bundle = fhir.get("Patient", params={"_count": "200", "_elements": "id"}).json()
    ids = [entry["resource"]["id"] for entry in bundle["entry"]]
    assert ids
    without = [pid for pid in ids if _count(fhir, "Encounter", patient=pid) == 0]
    assert without == []


def test_search_by_family_name(fhir: httpx.Client) -> None:
    first = fhir.get("Patient", params={"_count": "1"}).json()["entry"][0]["resource"]
    family = first["name"][0]["family"]
    found = fhir.get("Patient", params={"family": family}).json()
    assert first["id"] in {entry["resource"]["id"] for entry in found["entry"]}


def test_reloading_is_idempotent(fhir: httpx.Client) -> None:
    patients, organisations = _count(fhir, "Patient"), _count(fhir, "Organization")
    counts = load(fhir)  # organisation/practitioner bundles re-post as conditional creates
    assert counts["skipped"] == patients
    assert _count(fhir, "Patient") == patients
    assert _count(fhir, "Organization") == organisations
