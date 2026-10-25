"""The agent's tools: one interface, served by the MCP servers (SPEC section 5).

`McpTools` calls each server over streamable HTTP (guidelines-mcp, druggraph-mcp, fhir-mcp run as
services). Tests use in-memory fakes with the same interface.
"""

from typing import Any, Protocol, TypeVar

import anyio
from mcp import Client
from opentelemetry import trace
from pydantic import BaseModel, TypeAdapter

from agents.schemas import (
    CheckGroundingInput,
    CheckInteractionsInput,
    Evidence,
    GetPatientContextInput,
    GroundingReport,
    InteractionReport,
    LabParseResult,
    ParseLabReportInput,
    PatientSummary,
    SearchGuidelinesInput,
    WriteFhirInput,
    WriteFhirResult,
)

T = TypeVar("T")
_tracer = trace.get_tracer("clinscribe.tools")


class ToolError(Exception):
    """A tool refused or failed; the message is the server's reason."""


def server_reason(text: str, tool: str) -> str:
    """The server's own words: the MCP SDK prefixes "Error executing tool <name>: ", which the
    doctor saw in front of the refusal reason in the review screen."""
    prefix = f"Error executing tool {tool}: "
    return text[len(prefix) :] if text.startswith(prefix) else text


class Tools(Protocol):
    def search(self, request: SearchGuidelinesInput) -> list[Evidence]: ...
    def grounding(self, request: CheckGroundingInput) -> GroundingReport: ...
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
                text = " ".join(getattr(c, "text", "") for c in result.content)
                raise ToolError(server_reason(text, tool))
            content = result.structured_content or {}
            return TypeAdapter(out).validate_python(content.get("result", content))

        # one span per tool call, so a slow step shows up in the trace (incident 3 drill)
        with _tracer.start_as_current_span(f"mcp {tool}"):
            return anyio.run(run)

    def search(self, request: SearchGuidelinesInput) -> list[Evidence]:
        result: list[Evidence] = self._call(
            "guidelines", "search_guidelines", request, list[Evidence]
        )
        return result

    def grounding(self, request: CheckGroundingInput) -> GroundingReport:
        result: GroundingReport = self._call(
            "guidelines", "check_grounding", request, GroundingReport
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

    def parse_lab(self, request: ParseLabReportInput) -> LabParseResult:
        result: LabParseResult = self._call("fhir", "parse_lab_report", request, LabParseResult)
        return result
