"""MCP tool contracts (Phase 3 task 2), in-process with fakes: typed inputs and outputs, audited
reads, and writes refused unless the approval, the identifiers and the content all line up."""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
import pytest
from mcp import Client
from mcp.server.mcpserver import MCPServer
from pydantic import SecretStr

from agents.approval import approve
from apps.api.audit import AuditEntry
from mcp_servers.druggraph_mcp.server import build_server as druggraph_server
from mcp_servers.fhir_mcp.server import build_server as fhir_server
from mcp_servers.guidelines_mcp.server import build_server as guidelines_server
from privacy.deid.types import DeidentifiedText, issue
from retrieval.dense import Hit
from retrieval.graph.lexicon import DrugLexicon

KEY = SecretStr("k" * 64)
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
PATIENT = {
    "resourceType": "Patient",
    "id": "p-1",
    "birthDate": "1930-05-04",
    "gender": "female",
    "name": [{"family": "Kuhn96", "given": ["Ada"]}],
    "address": [{"city": "Springfield"}],
}
NOTE = {
    "resourceType": "DocumentReference",
    "status": "current",
    "subject": {"reference": "Patient/p-1"},
    "content": [{"attachment": {"contentType": "text/plain", "data": "U09BUA=="}}],
}
IDS = {"patient_id": "p-1", "birth_date": "1930-05-04", "family_name": "kuhn96"}


def call(server: MCPServer, tool: str, request: dict[str, Any]) -> tuple[bool, Any]:
    async def run() -> tuple[bool, Any]:
        async with Client(server) as client:
            result = await client.call_tool(tool, {"request": request})
            text = " ".join(getattr(c, "text", "") for c in result.content)
            return result.is_error, (text if result.is_error else result.structured_content)

    return anyio.run(run)


class FakeStore:
    def __init__(self) -> None:
        self.created: dict[str, dict[str, Any]] = {}

    def read(self, resource_type: str, resource_id: str) -> dict[str, Any] | None:
        return PATIENT if (resource_type, resource_id) == ("Patient", "p-1") else None

    def search(self, resource_type: str, params: dict[str, str]) -> list[dict[str, Any]]:
        assert params["patient"] == "p-1"
        concepts: dict[str, dict[str, Any]] = {
            "Condition": {"code": {"coding": [{"code": "44054006", "display": "Diabetes"}]}},
            "MedicationRequest": {
                "medicationCodeableConcept": {
                    "coding": [{"code": "860975", "display": "Metformin"}]
                }
            },
            "AllergyIntolerance": {"code": {"text": "Penicillin"}},
        }
        concept = concepts[resource_type]
        return [concept, concept]  # duplicates collapse

    def create(self, resource: dict[str, Any], if_none_exist: str) -> tuple[str, bool]:
        if if_none_exist in self.created:
            return self.created[if_none_exist]["id"], False
        self.created[if_none_exist] = {**resource, "id": f"doc-{len(self.created) + 1}"}
        return self.created[if_none_exist]["id"], True


class FakeAudit:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    def append(self, entry: AuditEntry) -> int:
        self.entries.append(entry)
        return len(self.entries)


@pytest.fixture
def fhir() -> tuple[MCPServer, FakeStore, FakeAudit]:
    store, audit = FakeStore(), FakeAudit()
    return fhir_server(store, audit, KEY, clock=lambda: NOW), store, audit


def _write(
    resource: Mapping[str, Any],
    token_resource: Mapping[str, Any] | None = None,
    ids: Mapping[str, str] = IDS,
    now: datetime = NOW,
    key: SecretStr = KEY,
) -> dict[str, Any]:
    token = approve("draft-7", dict(token_resource or resource), "p-1", "dr-house", key, now=now)
    return {
        "resource": dict(resource),
        "approval": token.model_dump(mode="json"),
        "identifiers": dict(ids),
    }


def test_patient_context_is_minimal_and_audited(
    fhir: tuple[MCPServer, FakeStore, FakeAudit],
) -> None:
    server, _, audit = fhir
    error, summary = call(
        server,
        "get_patient_context",
        {"patient_id": "p-1", "requested_by": "dr-house", "role": "doctor"},
    )
    assert not error
    assert summary["age_years"] == 90  # born 1930: 96, capped at 90
    assert [c["display"] for c in summary["conditions"]] == ["Diabetes"]
    assert summary["medications"][0]["code"] == "860975"
    assert summary["allergies"][0]["display"] == "Penicillin"
    for identifying in ("Kuhn96", "1930", "Springfield"):  # name, birth year, address
        assert identifying not in str(summary)
    assert [(e.actor, e.action, e.resource_id) for e in audit.entries] == [
        ("dr-house", "fhir.read", "p-1")
    ]


def test_unknown_patient_is_a_readable_error(fhir: tuple[MCPServer, FakeStore, FakeAudit]) -> None:
    error, message = call(
        fhir[0],
        "get_patient_context",
        {"patient_id": "nobody", "requested_by": "dr", "role": "doctor"},
    )
    assert error
    assert "no patient nobody" in message


def test_approved_write_is_created_once_and_audited(
    fhir: tuple[MCPServer, FakeStore, FakeAudit],
) -> None:
    server, store, audit = fhir
    request = _write(NOTE)
    error, result = call(server, "write_fhir", request)
    assert not error
    assert result == {"resource_type": "DocumentReference", "resource_id": "doc-1"}
    written = next(iter(store.created.values()))
    assert {"system": "urn:clinscribe:draft", "value": "draft-7"} in written["identifier"]
    error, again = call(server, "write_fhir", request)  # replay of the same approval
    assert not error
    assert again["resource_id"] == "doc-1"
    assert len(store.created) == 1
    assert [e.action for e in audit.entries] == ["fhir.write", "fhir.write.duplicate"]


@pytest.mark.parametrize(
    ("make", "reason"),
    [
        (lambda: _write(NOTE, key=SecretStr("x" * 64)), "signature"),
        (lambda: _write(NOTE, now=NOW - timedelta(minutes=11)), "expired"),
        (lambda: _write({**NOTE, "status": "superseded"}, token_resource=NOTE), "differs"),
        (lambda: _write(NOTE, ids={**IDS, "family_name": "Smith"}), "identifiers"),
        (lambda: _write(NOTE, ids={**IDS, "birth_date": "1930-05-05"}), "identifiers"),
        (lambda: _write({**NOTE, "subject": {"reference": "Patient/p-2"}}), "not about"),
        (lambda: _write({"resourceType": "Patient", "id": "p-1"}), "not writable"),
    ],
)
def test_writes_are_refused_with_a_reason_and_audited(
    fhir: tuple[MCPServer, FakeStore, FakeAudit], make: Any, reason: str
) -> None:
    server, store, audit = fhir
    error, message = call(server, "write_fhir", make())
    assert error
    assert "write refused" in message
    assert reason in message
    assert store.created == {}
    assert [e.action for e in audit.entries] == ["fhir.write.refused"]


def test_write_without_an_approval_is_rejected_by_the_contract(
    fhir: tuple[MCPServer, FakeStore, FakeAudit],
) -> None:
    server, store, _ = fhir
    error, message = call(server, "write_fhir", {"resource": NOTE, "identifiers": IDS})
    assert error
    assert "approval" in message
    assert store.created == {}


class FakeGraph:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, statement: str, **params: Any) -> list[dict[str, Any]]:
        self.calls.append(params["keys"])
        return [{"a": "Clarithromycin", "b": "Warfarin", "level": "Major"}]


LEXICON = DrugLexicon(
    [
        {"ddinter_id": "D1", "name": "Warfarin", "ingredient": "warfarin", "brands": ["Coumadin"]},
        {
            "ddinter_id": "D2",
            "name": "Clarithromycin",
            "ingredient": "clarithromycin",
            "brands": [],
        },
    ]
)


def test_interactions_report_pairs_and_unknown_drugs() -> None:
    graph = FakeGraph()
    error, report = call(
        druggraph_server(graph, LEXICON),
        "check_interactions",
        {"drugs": ["Coumadin", "clarithromycin", "dabigatran"]},
    )
    assert not error
    assert report["unknown_drugs"] == ["dabigatran"]
    (fact,) = report["interactions"]
    assert (fact["severity"], fact["source_id"]) == (
        "Major",
        "graph:ddinter:Clarithromycin|Warfarin",
    )
    assert graph.calls == [["D1", "D2"]]


def test_one_known_drug_is_not_queried() -> None:
    graph = FakeGraph()
    _, report = call(
        druggraph_server(graph, LEXICON), "check_interactions", {"drugs": ["warfarin", "zzz"]}
    )
    assert report == {"interactions": [], "unknown_drugs": ["zzz"]}
    assert graph.calls == []


CHUNKS = {
    "fda:w#s1#c0": {
        "text": "Start 2 to 5 mg.",
        "title": "Warfarin label",
        "section": "Dosage",
        "source": "openfda",
        "url": "https://dailymed.nlm.nih.gov/w",
        "topic": "anticoagulation",
    },
    "who:x#s2#c1": {
        "text": "Monitor INR.",
        "title": "WHO",
        "section": "Care",
        "source": "who",
        "url": "https://iris.who.int/x",
        "topic": "anticoagulation",
    },
}


class FakeSearcher:
    def __init__(self) -> None:
        self.queries: list[tuple[DeidentifiedText, int]] = []

    def search(self, query: DeidentifiedText, k: int = 10) -> list[Hit]:
        self.queries.append((query, k))
        return [Hit(chunk_id="who:x#s2#c1", score=0.9), Hit(chunk_id="fda:w#s1#c0", score=0.8)]


def test_search_returns_evidence_from_a_deidentified_query() -> None:
    searcher, seen = FakeSearcher(), []

    def deidentify(text: str) -> DeidentifiedText:
        seen.append(text)
        return issue(text.replace("Ada", "PATIENT_1"), "deid-service")

    server = guidelines_server(searcher, CHUNKS, deidentify)
    error, result = call(
        server, "search_guidelines", {"query": "Ada on warfarin: starting dose?", "k": 2}
    )
    assert not error
    assert [e["chunk_id"] for e in result["result"]] == ["who:x#s2#c1", "fda:w#s1#c0"]
    assert result["result"][1]["source_url"].startswith("https://")
    assert seen == ["Ada on warfarin: starting dose?"]
    assert searcher.queries[0][0].text == "PATIENT_1 on warfarin: starting dose?"
    _, filtered = call(
        server,
        "search_guidelines",
        {"query": "warfarin dose", "k": 2, "filters": {"sources": ["openfda"]}},
    )
    assert [e["chunk_id"] for e in filtered["result"]] == ["fda:w#s1#c0"]
    assert searcher.queries[1][1] == 50  # filters search deeper, then keep k
