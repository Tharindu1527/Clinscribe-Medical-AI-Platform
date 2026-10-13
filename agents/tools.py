"""The agent's tools: one interface, served by the MCP servers (SPEC section 5).

`McpTools` calls each server over streamable HTTP (guidelines-mcp, druggraph-mcp, fhir-mcp run as
services). Tests use in-memory fakes with the same interface.
"""

from typing import Any, Protocol, TypeVar

import anyio
from mcp import Client
from pydantic import BaseModel, TypeAdapter

from agents.schemas import (
    CheckInteractionsInput,
    Evidence,
    GetPatientContextInput,
    InteractionReport,
    PatientSummary,
    SearchGuidelinesInput,
    WriteFhirInput,
    WriteFhirResult,
)

T = TypeVar("T")


class ToolError(Exception):
    """A tool refused or failed; the message is the server's reason."""


class Tools(Protocol):
    def search(self, request: SearchGuidelinesInput) -> list[Evidence]: ...
    def interactions(self, request: CheckInteractionsInput) -> InteractionReport: ...
    def patient_context(self, request: GetPatientContextInput) -> PatientSummary: ...
    def write(self, request: WriteFhirInput) -> WriteFhirResult: ...


class McpTools:
    def __init__(self, guidelines_url: str, druggraph_url: str, fhir_url: str) -> None:
        self._urls = {"guidelines": guidelines_url, "druggraph": druggraph_url, "fhir": fhir_url}

    def _call(self, server: str, tool: str, request: BaseModel, out: Any) -> Any:
        async def run() -> Any:
            async with Client(self._urls[server], read_timeout_seconds=120) as client:
                result = await client.call_tool(tool, {"request": request.model_dump(mode="json")})
            if result.is_error:
                raise ToolError(" ".join(getattr(c, "text", "") for c in result.content))
            content = result.structured_content or {}
            return TypeAdapter(out).validate_python(content.get("result", content))

        return anyio.run(run)

    def search(self, request: SearchGuidelinesInput) -> list[Evidence]:
        result: list[Evidence] = self._call(
            "guidelines", "search_guidelines", request, list[Evidence]
        )
        return result

    def interactions(self, request: CheckInteractionsInput) -> InteractionReport:
        result: InteractionReport = self._call(
            "druggraph", "check_interactions", request, InteractionReport
        )
        return result

    def patient_context(self, request: GetPatientContextInput) -> PatientSummary:
        result: PatientSummary = self._call("fhir", "get_patient_context", request, PatientSummary)
        return result

    def write(self, request: WriteFhirInput) -> WriteFhirResult:
        result: WriteFhirResult = self._call("fhir", "write_fhir", request, WriteFhirResult)
        return result
