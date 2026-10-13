"""fhir-mcp: patient context and approved clinical writes over MCP (SPEC section 5; Phase 3 task 2).

Tools
- get_patient_context: the minimum necessary summary of one patient (age band, sex, active
  conditions, active medications, allergies); no name, birth date or address leaves this server.
  Every read is written to the audit log with the requesting user.
- write_fhir: creates a resource only with a valid approval token for exactly this resource, after
  checking two patient identifiers (id + birth date + family name) against the record and that the
  resource is about that patient. The create is conditional on the draft id, so replaying a token
  does not write twice. Every write is audited; refusals are audited too.

  uv run python -m mcp_servers.fhir_mcp [--http HOST:PORT]   (needs HAPI FHIR and Postgres)
"""

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, Protocol

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import SecretStr

from agents.approval import ApprovalError, verify
from agents.schemas import (
    CodedItem,
    GetPatientContextInput,
    PatientIdentifiers,
    PatientSummary,
    WriteFhirInput,
    WriteFhirResult,
)
from apps.api.audit import AuditEntry

DRAFT_SYSTEM = "urn:clinscribe:draft"
WRITABLE = {"DocumentReference", "Observation", "MedicationStatement", "AllergyIntolerance"}


class FhirStore(Protocol):
    def read(self, resource_type: str, resource_id: str) -> dict[str, Any] | None: ...
    def search(self, resource_type: str, params: dict[str, str]) -> list[dict[str, Any]]: ...
    def create(self, resource: dict[str, Any], if_none_exist: str) -> tuple[str, bool]: ...


class Audit(Protocol):
    def append(self, entry: AuditEntry) -> int: ...


class HttpFhirStore:
    def __init__(self, base_url: str, transport: httpx.BaseTransport | None = None) -> None:
        # no-cache: HAPI caches searches for ~60 s, which hid fresh writes (PROGRESS 2026-10-06)
        self._http = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            headers={"Accept": "application/fhir+json", "Cache-Control": "no-cache"},
            timeout=30,
            transport=transport,
        )

    def read(self, resource_type: str, resource_id: str) -> dict[str, Any] | None:
        response = self._http.get(f"{resource_type}/{resource_id}")
        if response.status_code in (404, 410):
            return None
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        return body

    def search(self, resource_type: str, params: dict[str, str]) -> list[dict[str, Any]]:
        response = self._http.get(resource_type, params={**params, "_count": "200"})
        response.raise_for_status()
        return [e["resource"] for e in response.json().get("entry", [])]

    def create(self, resource: dict[str, Any], if_none_exist: str) -> tuple[str, bool]:
        response = self._http.post(
            resource["resourceType"],
            json=resource,
            headers={"Content-Type": "application/fhir+json", "If-None-Exist": if_none_exist},
        )
        response.raise_for_status()
        created = response.status_code == 201
        location = response.headers.get("Location") or response.headers.get("Content-Location", "")
        if location:
            resource_id = location.split(f"{resource['resourceType']}/", 1)[1].split("/", 1)[0]
        else:
            resource_id = str(response.json()["id"])
        return resource_id, created


def _first_coding(concept: dict[str, Any] | None) -> CodedItem | None:
    if not concept:
        return None
    coding = (concept.get("coding") or [{}])[0]
    display = coding.get("display") or concept.get("text")
    return CodedItem(code=coding.get("code"), display=display) if display else None


def age_years(birth: date, today: date) -> int:
    years = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
    return min(max(years, 0), 90)  # Safe Harbor: 90 and over are reported as 90


def summarise(
    patient: dict[str, Any],
    conditions: list[dict[str, Any]],
    medications: list[dict[str, Any]],
    allergies: list[dict[str, Any]],
    today: date,
) -> PatientSummary:
    gender = patient.get("gender", "unknown")
    items = [
        [_first_coding(c.get("code")) for c in conditions],
        [_first_coding(m.get("medicationCodeableConcept")) for m in medications],
        [_first_coding(a.get("code")) for a in allergies],
    ]
    unique = [list({i.display: i for i in group if i}.values()) for group in items]
    return PatientSummary(
        patient_id=patient["id"],
        age_years=age_years(date.fromisoformat(patient["birthDate"]), today),
        sex=gender if gender in ("female", "male", "other") else "unknown",
        conditions=unique[0],
        medications=unique[1],
        allergies=unique[2],
    )


def identifiers_match(patient: dict[str, Any] | None, ids: PatientIdentifiers) -> bool:
    if not patient or patient.get("id") != ids.patient_id:
        return False
    if patient.get("birthDate") != ids.birth_date.isoformat():
        return False
    families = {str(n.get("family", "")).strip().lower() for n in patient.get("name", [])}
    return ids.family_name.strip().lower() in families


def about_patient(resource: dict[str, Any], patient_id: str) -> bool:
    reference = (resource.get("subject") or resource.get("patient") or {}).get("reference")
    return reference == f"Patient/{patient_id}"


def build_server(
    store: FhirStore,
    audit: Audit,
    approval_key: SecretStr,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> MCPServer:
    server = MCPServer("fhir-mcp", instructions="Patient context and approved clinical writes.")

    @server.tool()
    def get_patient_context(request: GetPatientContextInput) -> PatientSummary:
        """Minimum necessary summary of one patient. Every call is audited."""
        patient = store.read("Patient", request.patient_id)
        if patient is None:
            raise ToolError(f"no patient {request.patient_id}")
        pid = request.patient_id
        summary = summarise(
            patient,
            store.search("Condition", {"patient": pid, "clinical-status": "active"}),
            store.search("MedicationRequest", {"patient": pid, "status": "active"}),
            store.search("AllergyIntolerance", {"patient": pid}),
            clock().date(),
        )
        audit.append(
            AuditEntry(
                actor=request.requested_by,
                role=request.role,
                action="fhir.read",
                resource_type="Patient",
                resource_id=pid,
                details={"tool": "get_patient_context"},
            )
        )
        return summary

    @server.tool()
    def write_fhir(request: WriteFhirInput) -> WriteFhirResult:
        """Create a resource. Refused without a valid approval token for exactly this resource."""
        claims = request.approval.claims

        def refuse(reason: str) -> ToolError:
            audit.append(
                AuditEntry(
                    actor=claims.approver,
                    role="doctor",
                    action="fhir.write.refused",
                    resource_type=str(request.resource.get("resourceType")),
                    resource_id=None,
                    details={"draft_id": claims.draft_id, "reason": reason},
                )
            )
            return ToolError(f"write refused: {reason}")

        try:
            verify(request.approval, approval_key, now=clock(), content=request.resource)
        except ApprovalError as exc:
            raise refuse(str(exc)) from None
        resource_type = request.resource["resourceType"]
        if resource_type not in WRITABLE:
            raise refuse(f"{resource_type} is not writable through this tool")
        if not identifiers_match(
            store.read("Patient", request.identifiers.patient_id), request.identifiers
        ):
            raise refuse("patient identifiers do not match the record")
        if not about_patient(request.resource, request.identifiers.patient_id):
            raise refuse("resource is not about the identified patient")
        resource = dict(request.resource)
        identifier = {"system": DRAFT_SYSTEM, "value": claims.draft_id}
        resource["identifier"] = [*resource.get("identifier", []), identifier]
        resource_id, created = store.create(
            resource, if_none_exist=f"identifier={DRAFT_SYSTEM}|{claims.draft_id}"
        )
        audit.append(
            AuditEntry(
                actor=claims.approver,
                role="doctor",
                action="fhir.write" if created else "fhir.write.duplicate",
                resource_type=resource_type,
                resource_id=resource_id,
                details={"draft_id": claims.draft_id, "draft_sha256": claims.draft_sha256},
            )
        )
        return WriteFhirResult(resource_type=resource_type, resource_id=resource_id)

    return server


def main(argv: list[str] | None = None) -> None:
    from apps.api.audit import AuditLog
    from config.db import app_conninfo
    from config.settings import Settings
    from mcp_servers.serve import http_address, run

    address = http_address(argv, "fhir-mcp")
    settings = Settings()
    server = build_server(
        HttpFhirStore(settings.fhir_base_url),
        AuditLog(app_conninfo(settings), settings.audit_chain_key),
        settings.approval_token_key,
    )
    run(server, address)
