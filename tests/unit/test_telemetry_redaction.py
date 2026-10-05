"""Spans and logs leave a service with no structured PHI and no content attributes."""

import logging
from pathlib import Path

import pytest
import yaml
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from llmops.telemetry.redaction import (
    ALLOWED_KEYS,
    RedactingSpanExporter,
    RedactionFilter,
    scrub,
)

COLLECTOR = Path(__file__).resolve().parents[2] / "llmops" / "telemetry" / "collector.yaml"
SEEDED = {"ssn": "123-45-6789", "phone": "617-555-0142", "email": "jo.doe@example.org"}


def test_scrub_masks_structured_phi_and_keeps_clinical_text() -> None:
    text = f"SSN {SEEDED['ssn']}, call {SEEDED['phone']}, email {SEEDED['email']}; BP 142/88."
    out = scrub(text)
    assert all(value not in out for value in SEEDED.values())
    assert "[SSN]" in out
    assert "[PHONE]" in out
    assert "BP 142/88" in out


def test_span_keeps_only_allowed_keys_and_scrubs_values() -> None:
    memory = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(RedactingSpanExporter(memory)))
    tracer = provider.get_tracer("test")

    with tracer.start_as_current_span(f"lookup {SEEDED['phone']}") as span:
        span.set_attribute("gen_ai.request.model", "clinscribe-default")
        span.set_attribute("gen_ai.usage.input_tokens", 12)
        span.set_attribute("url.path", f"/patients/{SEEDED['ssn']}")
        span.set_attribute("gen_ai.prompt", f"Patient email {SEEDED['email']}")  # content key
        span.set_attribute("patient.phone", SEEDED["phone"])  # unknown key
        span.add_event("note", {"url.path": f"/x/{SEEDED['phone']}", "body": "free text"})

    (exported,) = memory.get_finished_spans()
    attrs = dict(exported.attributes or {})
    assert attrs["gen_ai.request.model"] == "clinscribe-default"
    assert attrs["gen_ai.usage.input_tokens"] == 12
    assert attrs["url.path"] == "/patients/[SSN]"
    assert "gen_ai.prompt" not in attrs
    assert "patient.phone" not in attrs
    assert attrs["clinscribe.redacted_attributes"] == 2
    assert SEEDED["phone"] not in exported.name
    event_attrs = dict(exported.events[0].attributes or {})
    assert event_attrs == {"url.path": "/x/[PHONE]", "clinscribe.redacted_attributes": 1}


def test_log_records_are_scrubbed(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("clinscribe.test")
    logger.addFilter(RedactionFilter())
    with caplog.at_level(logging.INFO, logger="clinscribe.test"):
        logger.info("lookup for %s failed", SEEDED["phone"])
    assert SEEDED["phone"] not in caplog.text
    assert "[PHONE]" in caplog.text


def test_collector_allow_list_matches_python_allow_list() -> None:
    config = yaml.safe_load(COLLECTOR.read_text(encoding="utf-8"))
    collector_keys = set(config["processors"]["redaction"]["allowed_keys"])
    assert collector_keys == set(ALLOWED_KEYS)
    assert config["processors"]["redaction"]["allow_all_keys"] is False
    assert "redaction" in config["service"]["pipelines"]["traces"]["processors"]
