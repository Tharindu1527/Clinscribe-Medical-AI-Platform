"""PROGRESS Phase 3 task 2 gate: each MCP server runs as a subprocess over stdio against the real
stack. fhir-mcp reads a Synthea patient (and the read is audited) and writes only with a valid
approval; druggraph-mcp and guidelines-mcp answer from Neo4j and the chosen retrieval pipeline.

fhir-mcp needs `just up` and `just fhir-load`; the other two also need `just up rag` (skipped
otherwise unless CLINSCRIBE_REQUIRE_RAG=1).
"""

import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

import anyio
import httpx
import psycopg
import pytest
from mcp import Client, StdioServerParameters

from agents.approval import approve
from config.db import app_conninfo
from config.settings import Settings

ROOT = Path(__file__).resolve().parents[2]


def call(module: str, tool: str, request: dict[str, Any]) -> tuple[bool, Any]:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", module], cwd=str(ROOT), env=dict(os.environ)
    )

    async def run() -> tuple[bool, Any]:
        async with Client(params, read_timeout_seconds=300) as client:
            result = await client.call_tool(tool, {"request": request})
            text = " ".join(getattr(c, "text", "") for c in result.content)
            return result.is_error, (text if result.is_error else result.structured_content)

    return anyio.run(run)


@pytest.fixture(scope="module")
def patient(stack: list[dict[str, str]]) -> dict[str, Any]:
    settings = Settings()
    response = httpx.get(
        f"{settings.fhir_base_url}/Patient",
        params={"_count": "1"},
        timeout=30,
        headers={"Cache-Control": "no-cache"},
    )
    response.raise_for_status()
    entries = response.json().get("entry", [])
    if not entries:
        pytest.fail("no Synthea patients on the FHIR server (just fhir-load)")
    resource: dict[str, Any] = entries[0]["resource"]
    return resource


def _audit_count(action: str, resource_id: str | None = None) -> int:
    with psycopg.connect(app_conninfo(Settings()), connect_timeout=10) as conn:
        row = conn.execute(
            "SELECT count(*) FROM audit_log "
            "WHERE action = %s AND (%s::text IS NULL OR resource_id = %s)",
            (action, resource_id, resource_id),
        ).fetchone()
    return int(row[0]) if row else 0


def test_fhir_read_over_stdio_is_minimal_and_audited(patient: dict[str, Any]) -> None:
    before = _audit_count("fhir.read", patient["id"])
    error, summary = call(
        "mcp_servers.fhir_mcp",
        "get_patient_context",
        {"patient_id": patient["id"], "requested_by": "itest-doctor", "role": "doctor"},
    )
    assert not error, summary
    assert summary["patient_id"] == patient["id"]
    assert 0 <= summary["age_years"] <= 90
    assert patient["name"][0]["family"] not in str(summary)
    assert patient["birthDate"] not in str(summary)
    assert _audit_count("fhir.read", patient["id"]) == before + 1


def test_fhir_write_over_stdio_needs_approval_and_both_identifiers(patient: dict[str, Any]) -> None:
    settings = Settings()
    resource = {
        "resourceType": "DocumentReference",
        "status": "current",
        "subject": {"reference": f"Patient/{patient['id']}"},
        "description": "Integration test note (synthetic)",
        "content": [{"attachment": {"contentType": "text/plain", "data": "U3ludGhldGljIG5vdGU="}}],
    }
    identifiers = {
        "patient_id": patient["id"],
        "birth_date": date.fromisoformat(patient["birthDate"]).isoformat(),
        "family_name": patient["name"][0]["family"],
    }
    token = approve(
        "itest-draft-1", resource, patient["id"], "itest-doctor", settings.approval_token_key
    )
    request = {
        "resource": resource,
        "approval": token.model_dump(mode="json"),
        "identifiers": identifiers,
    }
    error, first = call("mcp_servers.fhir_mcp", "write_fhir", request)
    assert not error, first
    error, again = call("mcp_servers.fhir_mcp", "write_fhir", request)
    assert not error
    assert again["resource_id"] == first["resource_id"]  # replay does not write twice
    wrong = {**request, "identifiers": {**identifiers, "family_name": "Nobody"}}
    error, message = call("mcp_servers.fhir_mcp", "write_fhir", wrong)
    assert error
    assert "identifiers do not match" in message


def _require_rag() -> None:
    try:
        httpx.get("http://127.0.0.1:7474", timeout=5).raise_for_status()
        httpx.get("http://127.0.0.1:6333/readyz", timeout=5).raise_for_status()
    except httpx.HTTPError:
        if os.environ.get("CLINSCRIBE_REQUIRE_RAG") == "1":
            pytest.fail("rag profile not running (just up rag)")
        pytest.skip("rag profile not running (just up rag)")


def test_druggraph_over_stdio(stack: list[dict[str, str]]) -> None:
    _require_rag()
    error, report = call(
        "mcp_servers.druggraph_mcp",
        "check_interactions",
        {"drugs": ["warfarin", "clarithromycin", "dabigatran"]},
    )
    assert not error, report
    assert report["unknown_drugs"] == ["dabigatran"]  # not in DDInter (PROGRESS task 9)
    assert any(
        {i["drug_a"], i["drug_b"]} == {"Clarithromycin", "Warfarin"} for i in report["interactions"]
    )


def test_guidelines_over_stdio(stack: list[dict[str, str]]) -> None:
    _require_rag()
    error, result = call(
        "mcp_servers.guidelines_mcp",
        "search_guidelines",
        {"query": "What is the usual starting dose of warfarin?", "k": 5},
    )
    assert not error, result
    evidence = result["result"]
    assert len(evidence) == 5
    assert all(e["source_url"].startswith("https://") for e in evidence)
    assert any("warfarin" in e["text"].lower() for e in evidence)
