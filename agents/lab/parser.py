"""Lab-report parser (Phase 5; SPEC section 2 Lab mode). Deterministic: no model sees lab values.

PDF text (pypdf) -> header (patient name, birth date, collection date) and result rows
"name | value | unit | reference" -> tests matched by printed name to LOINC
(config/lab_reference.yaml) -> FHIR Observations with status "preliminary", the reference interval
and an H/L/N interpretation. Nothing is written here: the doctor confirms, then fhir-mcp writes each
Observation with an approval.
Rows that cannot be read are counted and returned, never guessed.
"""

import io
import re
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel
from pypdf import PdfReader

REFERENCE = Path(__file__).resolve().parents[2] / "config" / "lab_reference.yaml"
ROW = re.compile(
    r"^(?P<name>[^|]+?)\s*\|\s*(?P<value>-?\d+(?:\.\d+)?)\s*\|\s*(?P<unit>[^|]+?)\s*\|\s*(?P<ref>.*)$"
)


class LabResult(BaseModel):
    loinc: str | None  # None when the printed name is not a known test
    name: str
    value: float
    unit: str
    low: float | None
    high: float | None
    flag: Literal["H", "L", "N"] | None
    unit_matches: bool


class LabReport(BaseModel):
    patient_name: str | None
    birth_date: str | None
    collected: str | None
    results: list[LabResult]
    unreadable_rows: list[str]


def reference() -> dict[str, dict[str, Any]]:
    tests: dict[str, dict[str, Any]] = yaml.safe_load(REFERENCE.read_text(encoding="utf-8"))[
        "tests"
    ]
    return tests


def _field(text: str, label: str) -> str | None:
    match = re.search(rf"^{label}:\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else None


def parse(pdf: bytes) -> LabReport:
    text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)
    by_name = {info["name"].lower(): (code, info) for code, info in reference().items()}
    results, unreadable = [], []
    in_table = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.lower().startswith("test") and "|" in line:
            in_table = True
            continue
        if not in_table or not line or line.lower() == "end of report":
            continue
        match = ROW.match(line)
        if not match:
            unreadable.append(line)
            continue
        name, unit = match.group("name").strip(), match.group("unit").strip()
        code, info = by_name.get(name.lower(), (None, None))
        low = high = None
        ref = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)\s*$", match.group("ref"))
        if ref:
            low, high = float(ref.group(1)), float(ref.group(2))
        elif info:
            low, high = float(info["low"]), float(info["high"])
        value = float(match.group("value"))
        flag: Literal["H", "L", "N"] | None = None
        if low is not None and high is not None:
            flag = "H" if value > high else "L" if value < low else "N"
        results.append(
            LabResult(
                loinc=code,
                name=name,
                value=value,
                unit=unit,
                low=low,
                high=high,
                flag=flag,
                unit_matches=info is not None and unit == info["unit"],
            )
        )
    return LabReport(
        patient_name=_field(text, "Patient"),
        birth_date=_field(text, "Date of birth"),
        collected=_field(text, "Collected"),
        results=results,
        unreadable_rows=unreadable,
    )


def to_observation(result: LabResult, patient_id: str, collected: str | None) -> dict[str, Any]:
    """A preliminary FHIR Observation; only known tests with the expected unit are mapped."""
    if result.loinc is None or not result.unit_matches:
        raise ValueError(f"{result.name}: unknown test or unexpected unit {result.unit!r}")
    observation: dict[str, Any] = {
        "resourceType": "Observation",
        "status": "preliminary",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "laboratory",
                    }
                ]
            }
        ],
        "code": {
            "coding": [{"system": "http://loinc.org", "code": result.loinc, "display": result.name}]
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "valueQuantity": {
            "value": result.value,
            "unit": result.unit,
            "system": "http://unitsofmeasure.org",
            "code": result.unit,
        },
    }
    if collected:
        observation["effectiveDateTime"] = date.fromisoformat(collected).isoformat()
    if result.low is not None and result.high is not None:
        observation["referenceRange"] = [
            {
                "low": {"value": result.low, "unit": result.unit},
                "high": {"value": result.high, "unit": result.unit},
            }
        ]
    if result.flag:
        observation["interpretation"] = [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
                        "code": result.flag,
                    }
                ]
            }
        ]
    return observation


def identity_matches(report: LabReport, patient: dict[str, Any]) -> dict[str, bool]:
    """Wrong-patient control: the report's name and birth date against the chosen record."""
    names = {
        " ".join([*n.get("given", []), n.get("family", "")]).strip().lower()
        for n in patient.get("name", [])
    }
    return {
        "name": (report.patient_name or "").strip().lower() in names,
        "birth_date": report.birth_date == patient.get("birthDate"),
    }
