"""The dashboards on the running `obs` profile (ADR-0023): both data sources healthy, every panel's
query runs through Grafana without an error, a request to the API becomes span metrics in
Prometheus under its route template, and Grafana's database login reads only its columns.

Needs `just up obs` and `just migrate`; skipped otherwise unless CLINSCRIBE_REQUIRE_OBS=1.
"""

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest

from apps.api.auth import issue_token
from config.db import grafana_conninfo
from config.settings import Settings
from scripts.migrate import SPEND_COLUMNS

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
GRAFANA = "http://127.0.0.1:3000"
PROMETHEUS = "http://127.0.0.1:9090"
DASHBOARD = json.loads((ROOT / "infra/grafana/dashboards/clinscribe.json").read_text("utf-8"))


@pytest.fixture(scope="module")
def grafana(stack: list[dict[str, str]]) -> httpx.Client:
    client = httpx.Client(
        base_url=GRAFANA,
        auth=("admin", Settings().grafana_admin_password.get_secret_value()),
        timeout=60,
    )
    try:
        client.get("/api/health").raise_for_status()
    except httpx.HTTPError:
        if os.environ.get("CLINSCRIBE_REQUIRE_OBS") == "1":
            pytest.fail("Grafana is not running (just up obs)")
        pytest.skip("Grafana is not running (just up obs)")
    return client


def test_both_data_sources_are_healthy(grafana: httpx.Client) -> None:
    for uid in ("prometheus", "spendlog"):
        health = grafana.get(f"/api/datasources/uid/{uid}/health").json()
        assert health["status"] == "OK", (uid, health)
    plugins = {p["id"] for p in grafana.get("/api/plugins", params={"type": "datasource"}).json()}
    assert {"prometheus", "grafana-postgresql-datasource"} <= plugins  # the UI can render both


def test_every_panel_query_runs(grafana: httpx.Client) -> None:
    errors: list[tuple[str, str]] = []
    for panel in DASHBOARD["panels"]:
        for target in panel.get("targets", []):
            query: dict[str, Any] = {**target, "intervalMs": 15000, "maxDataPoints": 300}
            body = {"queries": [query], "from": "now-6h", "to": "now"}
            response = grafana.post("/api/ds/query", json=body)
            result = response.json().get("results", {}).get(target["refId"], {})
            if response.status_code != 200 or result.get("error"):
                errors.append((panel["title"], result.get("error") or response.text[:200]))
    assert errors == []


def test_a_request_becomes_span_metrics_under_its_route(grafana: httpx.Client) -> None:
    token = issue_token("dr-demo", Settings().auth_token_key)
    headers = {"Authorization": f"Bearer {token}"}
    httpx.get("http://127.0.0.1:8000/v1/drafts/draft-obs-check", headers=headers, timeout=30)
    selector = 'service_name="api", span_name="GET /v1/drafts/{draft_id}"'
    query = f"sum(traces_span_metrics_calls_total{{{selector}}})"
    deadline = time.monotonic() + 90  # flush every 15 s, scrape every 15 s
    while time.monotonic() < deadline:
        result = httpx.get(f"{PROMETHEUS}/api/v1/query", params={"query": query}, timeout=30)
        if result.json()["data"]["result"]:
            break
        time.sleep(5)
    else:
        pytest.fail("no span metrics for GET /v1/drafts/{draft_id} within 90 s")
    leaked = httpx.get(
        f"{PROMETHEUS}/api/v1/query",
        params={
            "query": 'count(traces_span_metrics_calls_total{span_name=~".*draft-obs-check.*"})'
        },
        timeout=30,
    ).json()["data"]["result"]
    assert leaked == []  # the id stays in the trace's url.path, never in a metric label


def test_grafanas_login_reads_only_its_spend_log_columns(grafana: httpx.Client) -> None:
    with psycopg.connect(grafana_conninfo(Settings())) as conn:
        columns = ", ".join(f'"{c}"' for c in SPEND_COLUMNS)
        conn.execute(f'SELECT {columns} FROM "LiteLLM_SpendLogs" LIMIT 1')  # noqa: S608
        for denied in ("messages", "response", "api_key"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(f'SELECT {denied} FROM "LiteLLM_SpendLogs" LIMIT 1')  # noqa: S608
            conn.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute('SELECT 1 FROM "LiteLLM_VerificationToken" LIMIT 1')
