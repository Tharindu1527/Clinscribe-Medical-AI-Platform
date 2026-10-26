"""Second line of PHI defence for traces and logs (SPEC section 7), behind privacy/deid.

Deny by default: a span keeps only allow-listed attribute keys, and every string it keeps is
scrubbed with the same structured-PHI regexes the de-ID service uses. Message content keys
(prompts, completions) are never on the list. The OTel collector applies the same allow-list
(llmops/telemetry/collector.yaml) to spans from services we do not control, such as LiteLLM.
"""

import logging
import re
from collections.abc import Sequence
from typing import Any

from opentelemetry.sdk.trace import Event, ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from privacy.deid.recognizers import PATTERNS

# Exact keys, kept in step with the collector's redaction processor by a unit test
ALLOWED_KEYS = frozenset(
    {
        "gen_ai.operation.name",
        "gen_ai.system",
        "gen_ai.request.model",
        "gen_ai.request.max_tokens",
        "gen_ai.request.temperature",
        "gen_ai.response.model",
        "gen_ai.response.id",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
        "http.request.method",
        "http.response.status_code",
        "url.path",
        "server.address",
        "server.port",
        "error.type",
        "clinscribe.cache_hit",
        "clinscribe.prompt_version",
        "clinscribe.encounter_id",
        "clinscribe.redacted_attributes",
        "service.name",  # resource attribute: the collector redacts resources too
    }
)

_COMPILED = [(entity, re.compile(p)) for entity, plist in PATTERNS.items() for p in plist]


def scrub(text: str) -> str:
    """Replace structured PHI (dates, phones, IDs, emails...) with [TYPE] markers."""
    for entity, regex in _COMPILED:

        def mask(match: re.Match[str], entity: str = entity) -> str:
            start, end = match.span("v")
            whole_start = match.start()
            return (
                match.group(0)[: start - whole_start]
                + f"[{entity}]"
                + match.group(0)[end - whole_start :]
            )

        text = regex.sub(mask, text)
    return text


def _clean_value(value: Any) -> Any:
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return tuple(scrub(v) if isinstance(v, str) else v for v in value)
    return value


def redact_attributes(attributes: Any) -> dict[str, Any]:
    kept = {k: _clean_value(v) for k, v in (attributes or {}).items() if k in ALLOWED_KEYS}
    dropped = len(attributes or {}) - len(kept)
    if dropped:
        kept["clinscribe.redacted_attributes"] = dropped
    return kept


def redact_span(span: ReadableSpan) -> ReadableSpan:
    events = [
        Event(scrub(e.name), redact_attributes(e.attributes), timestamp=e.timestamp)
        for e in span.events
    ]
    return ReadableSpan(
        name=scrub(span.name),
        context=span.context,
        parent=span.parent,
        resource=span.resource,
        attributes=redact_attributes(span.attributes),
        events=events,
        links=span.links,
        kind=span.kind,
        status=span.status,
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


class RedactingSpanExporter(SpanExporter):
    """Wraps a real exporter and redacts every span before it leaves the process."""

    def __init__(self, inner: SpanExporter) -> None:
        self._inner = inner

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        return self._inner.export([redact_span(s) for s in spans])

    def shutdown(self) -> None:
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._inner.force_flush(timeout_millis)


class RedactionFilter(logging.Filter):
    """Scrub structured PHI from log messages before any handler writes them.

    Positional arguments are scrubbed one by one and kept when the message they then make has
    nothing left to scrub, because some formatters unpack them (uvicorn's access log). Otherwise
    (PHI split between template and argument, a non-string argument, mapping arguments) the
    message is replaced by its scrubbed text and the arguments are dropped.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and record.args:
            args = tuple(scrub(arg) if isinstance(arg, str) else arg for arg in record.args)
            try:
                joined = str(record.msg) % args
            except (TypeError, ValueError):
                joined = None
            if joined is not None and scrub(joined) == joined:
                record.args = args
                return True
        record.msg = scrub(record.getMessage())
        record.args = None
        return True
