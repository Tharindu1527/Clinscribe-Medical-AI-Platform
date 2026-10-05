"""OpenTelemetry and logging set-up shared by every ClinScribe service.

Spans go: service -> RedactingSpanExporter -> OTel collector (second redaction pass) ->
Langfuse Cloud (ADR-0002) and a local file. Logs go to stdout through RedactionFilter.
"""

import logging
import sys
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from opentelemetry import propagate, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.trace import SpanKind

from llmops.telemetry.redaction import RedactingSpanExporter, RedactionFilter

LOGGERS = ("", "uvicorn", "uvicorn.access", "uvicorn.error", "clinscribe")


def configure_tracing(
    service_name: str, otlp_endpoint: str, exporter: SpanExporter | None = None
) -> TracerProvider:
    """Install a tracer provider whose spans are redacted before export."""
    inner = exporter or OTLPSpanExporter(endpoint=f"{otlp_endpoint.rstrip('/')}/v1/traces")
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(RedactingSpanExporter(inner)))
    trace.set_tracer_provider(provider)
    return provider


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler.addFilter(RedactionFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for name in LOGGERS[1:]:
        logger = logging.getLogger(name)
        logger.addFilter(RedactionFilter())  # records created on these loggers are scrubbed too


def instrument(app: FastAPI, service_name: str) -> None:
    """One SERVER span per request, continuing the caller's trace (W3C traceparent)."""
    tracer = trace.get_tracer(service_name)

    @app.middleware("http")
    async def _trace(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        context = propagate.extract(dict(request.headers))
        name = f"{request.method} {request.url.path}"
        with tracer.start_as_current_span(name, context=context, kind=SpanKind.SERVER) as span:
            span.set_attribute("http.request.method", request.method)
            span.set_attribute("url.path", request.url.path)
            response = await call_next(request)
            span.set_attribute("http.response.status_code", response.status_code)
            return response
