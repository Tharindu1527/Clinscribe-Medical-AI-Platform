from pathlib import Path

from scripts.fhir_load import SYNTHEA_ID_SYSTEM, bundle_order, sha256_of, synthea_patient_id


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
