"""FastAPI's own OpenTelemetry stays off, so spans leave only through the redacting exporter
(docs/postmortems/0004-fastapi-telemetry-bypassed-span-redaction.md). Each case runs in a fresh
interpreter: OpenTelemetry providers are global and can be set only once per process."""

import subprocess
import sys
from pathlib import Path

import pytest

from apps.api.main import app as api_app
from llmops.telemetry.setup import FASTAPI_TELEMETRY
from privacy.deid.app import app as deid_app

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[2]
PROBE = """
import os
os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://127.0.0.1:9"  # nothing listens; never reached
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry import _logs, metrics, trace
app = FastAPI({config})
@app.get("/x")
def x() -> dict[str, str]:
    return {{}}
with TestClient(app) as client:
    client.get("/x")
    providers = (
        trace.get_tracer_provider(), metrics.get_meter_provider(), _logs.get_logger_provider()
    )
    print(*(type(p).__name__ for p in providers), flush=True)
    os._exit(0)  # before shutdown flushes exports to the dead endpoint (they retry for ~30 s)
"""


def _providers(config: str) -> list[str]:
    out = subprocess.run(
        [sys.executable, "-c", PROBE.format(config=config)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    return out.stdout.split()


def test_fastapi_installs_no_exporters_with_the_project_setting() -> None:
    assert _providers(
        f"telemetry={FASTAPI_TELEMETRY!r}"
    ) == [  # the value, so the probe stays light
        "ProxyTracerProvider",
        "_ProxyMeterProvider",
        "ProxyLoggerProvider",
    ]


def test_control_fastapi_defaults_would_install_plain_exporters() -> None:
    # what the services did until 2026-10-24: their own providers, no redaction
    assert _providers("") == ["TracerProvider", "MeterProvider", "LoggerProvider"]


@pytest.mark.parametrize("app", [api_app, deid_app], ids=["api", "deid"])
def test_every_service_app_uses_the_setting(app: object) -> None:
    config = app._telemetry  # type: ignore[attr-defined]  # FastAPI keeps it here (0.142)
    assert {key: config[key] for key in FASTAPI_TELEMETRY} == FASTAPI_TELEMETRY


def test_tracing_fails_closed_when_another_provider_got_there_first() -> None:
    code = """
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from llmops.telemetry.setup import configure_tracing
trace.set_tracer_provider(TracerProvider())  # e.g. a framework's own, unredacted
try:
    configure_tracing("api", "http://127.0.0.1:9")
except RuntimeError as exc:
    print("refused:", exc)
"""
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120
    )
    assert out.stdout.startswith("refused: another tracer provider is installed"), out.stderr
