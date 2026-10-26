"""Dashboards (ADR-0023): spans named by route, health checks untraced, 5xx marked as errors; every
model call tagged with its encounter and the alias asked for, outside the replay-cache key and
across the graph's threads; the collector's metrics come from redacted spans only; the dashboard
queries only the metrics and spend-log columns that exist for it. No stack."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from llmops.gateway.client import ReplayCache, current_encounter, for_encounter
from llmops.telemetry.redaction import ALLOWED_KEYS
from llmops.telemetry.setup import instrument
from scripts.migrate import SPEND_COLUMNS
from tests.unit.test_agent_graph import (
    INJECTED,
    INR,
    WARFARIN,
    FakeTools,
    ScriptedChat,
    _agents,
    _cited,
)
from tests.unit.test_gateway_client import HELLO, _client, _ok_transport

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[2]
COLLECTOR = yaml.safe_load((ROOT / "llmops/telemetry/collector.yaml").read_text(encoding="utf-8"))
DASHBOARD = json.loads((ROOT / "infra/grafana/dashboards/clinscribe.json").read_text("utf-8"))
DATASOURCES = yaml.safe_load(
    (ROOT / "infra/grafana/provisioning/datasources/datasources.yaml").read_text(encoding="utf-8")
)


def _traced_app() -> tuple[TestClient, InMemorySpanExporter]:
    memory = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(memory))
    app = FastAPI()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/drafts/{draft_id}")
    def draft(draft_id: str) -> dict[str, str]:
        return {"draft_id": draft_id}

    @app.get("/v1/broken")
    def broken() -> None:
        raise HTTPException(502, "the model gateway failed")

    instrument(app, "api", provider)
    return TestClient(app), memory


def test_request_spans_are_named_by_route_and_health_checks_are_not_traced() -> None:
    client, memory = _traced_app()
    client.get("/health")
    client.get("/v1/drafts/draft-123")
    client.get("/v1/nothing-here/abc")
    client.get("/v1/broken")
    spans = memory.get_finished_spans()
    assert [s.name for s in spans] == [
        "GET /v1/drafts/{draft_id}",
        "GET unmatched",  # arbitrary paths would make one metric series each
        "GET /v1/broken",
    ]
    assert spans[0].attributes is not None
    assert spans[0].attributes["url.path"] == "/v1/drafts/draft-123"  # the trace keeps the path
    assert [s.status.status_code for s in spans] == [StatusCode.UNSET] * 2 + [StatusCode.ERROR]


def _sent(calls: list[httpx.Request]) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(calls[-1].content)
    return body


def test_each_call_names_the_alias_asked_for_and_its_encounter() -> None:
    calls: list[httpx.Request] = []
    client = _client(_ok_transport(calls))
    client.complete("clinscribe-default", HELLO)
    assert _sent(calls)["metadata"] == {
        "spend_logs_metadata": {"requested_alias": "clinscribe-default"}
    }
    with for_encounter("enc-7"):
        assert current_encounter() == "enc-7"
        client.complete("clinscribe-fallback-groq", HELLO)
    assert current_encounter() is None
    assert _sent(calls)["metadata"]["spend_logs_metadata"] == {
        "requested_alias": "clinscribe-fallback-groq",
        "encounter_id": "enc-7",
    }


def test_the_encounter_is_not_part_of_the_replay_cache_key(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    client = _client(_ok_transport(calls), cache=ReplayCache(tmp_path, "record"))
    with for_encounter("enc-a"):
        client.complete("clinscribe-default", HELLO)
    with for_encounter("enc-b"):
        client.complete("clinscribe-default", HELLO)  # same request: replayed, no network
    assert len(calls) == 1


def test_the_encounter_reaches_every_model_call_inside_the_graph() -> None:
    seen: list[str | None] = []

    class Recording(ScriptedChat):
        def complete(self, model: str, messages: Any, **kw: Any) -> Any:
            seen.append(current_encounter())
            return super().complete(model, messages, **kw)

    chat = Recording(
        grade=[{"relevant": ["S2"]}, {"relevant": ["S1", "S2"]}],
        rewrite=[{"query": "clarithromycin warfarin interaction INR"}],
        answer=[_cited(("Clarithromycin raises the INR on warfarin.", ["S2", "S3"]))],
    )
    graph = _agents(chat, FakeTools([WARFARIN, INR, INJECTED])).build()
    question = "Does clarithromycin interact with warfarin?"
    with for_encounter("ask-42"):
        graph.invoke({"mode": "ask", "encounter_id": "ask-42", "question": question})
    assert len(seen) == 4  # grade, rewrite, grade, answer: the agentic path
    assert set(seen) == {"ask-42"}


def test_metrics_come_from_the_redacted_spans_only() -> None:
    traces = COLLECTOR["service"]["pipelines"]["traces"]
    assert "redaction" in traces["processors"]
    assert "spanmetrics" in traces["exporters"]  # a connector: it sees the pipeline's output
    assert COLLECTOR["service"]["pipelines"]["metrics/spanmetrics"] == {
        "receivers": ["spanmetrics"],
        "exporters": ["prometheus"],
    }
    dimensions = {d["name"] for d in COLLECTOR["connectors"]["spanmetrics"]["dimensions"]}
    assert dimensions <= ALLOWED_KEYS
    assert COLLECTOR["exporters"]["file/traces"]["rotation"]["max_backups"] >= 1


LABELS = {
    "le",
    "service_name",
    "span_name",
    "span_kind",
    "status_code",
    "http_response_status_code",
    "gen_ai_request_model",
}
NOT_GRANTED = {  # LiteLLM_SpendLogs columns outside SPEND_COLUMNS, as of LiteLLM v1.104.0
    "messages",
    "response",
    "proxy_server_request",
    "api_key",
    "user",
    "end_user",
    "requester_ip_address",
    "request_tags",
    "session_id",
    "cache_key",
    "api_base",
    "team_id",
}


def _targets() -> list[dict[str, Any]]:
    return [t for p in DASHBOARD["panels"] for t in p.get("targets", [])]


def test_the_dashboard_uses_only_provisioned_data_sources() -> None:
    uids = {d["uid"] for d in DATASOURCES["datasources"]}
    used = {t["datasource"]["uid"] for t in _targets()}
    used |= {p["datasource"]["uid"] for p in DASHBOARD["panels"] if "datasource" in p}
    assert used == uids


def test_prometheus_queries_use_span_metrics_and_their_labels() -> None:
    import re

    for target in (t for t in _targets() if t["datasource"]["uid"] == "prometheus"):
        expr = target["expr"]
        metrics = set(re.findall(r"\b(traces_span_metrics_\w+)", expr))
        assert metrics, expr
        assert metrics <= {
            "traces_span_metrics_calls_total",
            "traces_span_metrics_duration_milliseconds_bucket",
        }
        used = set(re.findall(r"(\w+)\s*(?:=~|=)\s*\"", expr))
        for group in re.findall(r"by \(([^)]*)\)", expr):
            used |= {label.strip() for label in group.split(",")}
        assert used <= LABELS, expr


def test_spend_log_queries_read_only_the_granted_columns() -> None:
    import re

    for target in (t for t in _targets() if t["datasource"]["uid"] == "spendlog"):
        query = target["rawSql"]
        tables = set(re.findall(r'FROM\s+("?\w+"?)', query))
        assert tables, query
        assert tables <= {'"LiteLLM_SpendLogs"', "per"}, query  # "per": a CTE over that table
        words = {w.strip('"').lower() for w in re.findall(r'"?\b\w+\b"?', query)}
        assert not (words & NOT_GRANTED), (words & NOT_GRANTED, query)
        assert "metadata" not in words or "spend_logs_metadata" in query  # only that key of it
    assert len(SPEND_COLUMNS) == 10
