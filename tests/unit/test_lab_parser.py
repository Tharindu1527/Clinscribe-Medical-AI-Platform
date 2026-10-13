"""Lab parser (Phase 5): PDF round trip, flags, unknown tests, units, identity check."""

import pytest

from agents.lab.parser import identity_matches, parse, to_observation
from agents.lab.pdf import report_lines, write_pdf

ROWS = [
    ("Glucose", "84", "mg/dL", "70 - 99"),
    ("Potassium", "5.6", "mmol/L", "3.5 - 5.1"),
    ("Hemoglobin", "10.2", "g/dL", "12 - 17.5"),
    ("Mystery assay", "3", "units", "1 - 2"),
    ("Sodium", "140", "mg/dL", "135 - 145"),  # wrong unit for sodium
]
PDF = write_pdf(report_lines("Ada (Test) Kuhn96", "1930-05-04", "2025-09-09", ROWS))


def test_round_trip_reads_header_rows_and_flags() -> None:
    report = parse(PDF)
    assert (report.patient_name, report.birth_date, report.collected) == (
        "Ada (Test) Kuhn96",
        "1930-05-04",
        "2025-09-09",
    )
    flags = {r.name: r.flag for r in report.results}
    assert flags == {
        "Glucose": "N",
        "Potassium": "H",
        "Hemoglobin": "L",
        "Mystery assay": "H",
        "Sodium": "N",
    }
    assert report.unreadable_rows == []


def test_only_known_tests_with_the_expected_unit_become_observations() -> None:
    report = parse(PDF)
    by_name = {r.name: r for r in report.results}
    obs = to_observation(by_name["Potassium"], "p-1", report.collected)
    assert obs["code"]["coding"][0]["code"] == "6298-4"
    assert obs["status"] == "preliminary"
    assert obs["interpretation"][0]["coding"][0]["code"] == "H"
    assert obs["subject"] == {"reference": "Patient/p-1"}
    for name in ("Mystery assay", "Sodium"):
        with pytest.raises(ValueError, match="unknown test or unexpected unit"):
            to_observation(by_name[name], "p-1", report.collected)


def test_identity_check_catches_another_patient() -> None:
    report = parse(PDF)
    ada = {"birthDate": "1930-05-04", "name": [{"given": ["Ada", "(Test)"], "family": "Kuhn96"}]}
    other = {"birthDate": "1930-05-04", "name": [{"given": ["Bea"], "family": "Kuhn96"}]}
    assert identity_matches(report, ada) == {"name": True, "birth_date": True}
    assert identity_matches(report, other) == {"name": False, "birth_date": True}
