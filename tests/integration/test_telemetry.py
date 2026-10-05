"""PROGRESS task 7: a span carrying seeded fake PHI reaches the local export and Langfuse
without the PHI, and keeps its GenAI attributes."""

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from config.settings import Settings
from llmops.telemetry.redaction import RedactingSpanExporter

FILE_EXPORT = Path(__file__).resolve().parents[2] / ".artifacts" / "otel" / "traces.jsonl"
SEEDED_PHONE = "617-555-0142"
SEEDED_EMAIL = "jo.doe@example.org"


def _find_trace(trace_id: str, timeout_s: float = 30) -> list[str]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if FILE_EXPORT.exists():
            lines = [
                ln for ln in FILE_EXPORT.read_text(encoding="utf-8").splitlines() if trace_id in ln
            ]
            if lines:
                return lines
        time.sleep(1)
    return []


@pytest.fixture(scope="module")
def trace_id(stack: list[dict[str, str]]) -> str:
    settings = Settings()
    exporter = OTLPSpanExporter(endpoint=f"{settings.otel_exporter_otlp_endpoint}/v1/traces")
    provider = TracerProvider(resource=Resource.create({"service.name": "telemetry-test"}))
    provider.add_span_processor(SimpleSpanProcessor(RedactingSpanExporter(exporter)))
    tracer = provider.get_tracer("telemetry-test")
    with tracer.start_as_current_span(f"chat for {SEEDED_PHONE}") as span:
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.request.model", "clinscribe-default")
        span.set_attribute("gen_ai.usage.input_tokens", 21)
        span.set_attribute("gen_ai.usage.output_tokens", 5)
        span.set_attribute("url.path", f"/lookup/{SEEDED_PHONE}")
        span.set_attribute("gen_ai.prompt", f"email {SEEDED_EMAIL}")
        tid = format(span.get_span_context().trace_id, "032x")
    provider.shutdown()
    return tid


def test_local_export_has_genai_attributes_and_no_phi(trace_id: str) -> None:
    lines = _find_trace(trace_id)
    assert lines, "span not found in the collector's file export"
    exported = "\n".join(lines)
    assert SEEDED_PHONE not in exported
    assert SEEDED_EMAIL not in exported
    keys = {
        attr["key"]
        for line in lines
        for rs in json.loads(line)["resourceSpans"]
        for ss in rs["scopeSpans"]
        for sp in ss["spans"]
        for attr in sp.get("attributes", [])
    }
    assert {
        "gen_ai.request.model",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
    } <= keys
    assert "gen_ai.prompt" not in keys


def test_trace_arrives_in_langfuse_without_phi(trace_id: str) -> None:
    settings = Settings()
    auth = (
        settings.langfuse_public_key.get_secret_value(),
        settings.langfuse_secret_key.get_secret_value(),
    )
    if not auth[0]:
        pytest.fail("Langfuse keys are empty in .env")
    # Langfuse retired GET /api/public/traces for organisations created after 2026-09-16;
    # the v2 observations API is the supported way to read spans back.
    now = datetime.now(UTC)
    params = {
        "traceId": trace_id,
        "fromStartTime": (now - timedelta(minutes=30)).isoformat(),
        "toStartTime": (now + timedelta(minutes=5)).isoformat(),
    }
    deadline = time.monotonic() + 180  # Langfuse ingests asynchronously
    matches: list[dict[str, object]] = []
    body = ""
    while time.monotonic() < deadline and not matches:
        response = httpx.get(
            f"{settings.langfuse_host}/api/public/v2/observations",
            params=params,
            auth=auth,
            timeout=30,
        )
        response.raise_for_status()
        body = response.text
        matches = [o for o in response.json()["data"] if o.get("traceId") == trace_id]
        if not matches:
            time.sleep(10)
    assert matches, "trace not found in Langfuse within 180 s"
    assert SEEDED_PHONE not in body
    assert SEEDED_EMAIL not in body
