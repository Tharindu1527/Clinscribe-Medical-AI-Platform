"""The FHIR resource a SOAP note becomes on approval. Deterministic, so the API can hash exactly
what will be written before the doctor's approval token is signed (agents/approval.py)."""

import base64
from typing import Any

from agents.schemas import SoapNote

SECTIONS = ("subjective", "objective", "assessment", "plan")


def render(note: SoapNote) -> str:
    lines = ["AI-generated draft, reviewed and approved by the clinician (ClinScribe)."]
    for section in SECTIONS:
        items = [s.text for s in note.statements if s.section == section]
        if items:
            lines += ["", section.upper(), *(f"- {text}" for text in items)]
    return "\n".join(lines) + "\n"


def note_to_resource(note: SoapNote, patient_id: str) -> dict[str, Any]:
    data = base64.b64encode(render(note).encode()).decode()
    return {
        "resourceType": "DocumentReference",
        "status": "current",
        "type": {
            "coding": [
                {"system": "http://loinc.org", "code": "11506-3", "display": "Progress note"}
            ]
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "description": (
            f"SOAP note, encounter {note.encounter_id} ({note.prompt_version}, {note.model})"
        ),
        "content": [{"attachment": {"contentType": "text/plain; charset=utf-8", "data": data}}],
    }
