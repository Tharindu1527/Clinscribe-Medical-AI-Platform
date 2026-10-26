"""Tracing backends compared on the same traffic (ADR-0024; SPEC section 7: "Arize Phoenix is tried
once and compared"): Langfuse Cloud (the configured backend, ADR-0002) and self-hosted Phoenix,
both fed the collector's redacted spans, against the collector's local file export.

One synthetic consultation goes through the API with the real models: a Scribe draft (rejected
afterwards) and three Ask questions. Each request's trace id comes from its audit row. For every
trace: spans in the file export, in Phoenix and in Langfuse; for the model-call spans, what each
backend shows of the model and token counts; then Phoenix's memory, disk and start-up.

  uv run python -m evals.llmops.tracing_compare
  (needs `just up rag` and `just phoenix on`; about 8 real model calls)
Writes evals/reports/llmops/tracing_backends.md.
"""

import json
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import psycopg

from apps.api.auth import issue_token
from config.db import app_conninfo
from config.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "evals" / "reports" / "llmops" / "tracing_backends.md"
API = "http://127.0.0.1:8000"
PHOENIX = "http://127.0.0.1:6006"
FILE_EXPORT = ROOT / ".artifacts" / "otel"
QUESTIONS = [
    "What is the usual starting dose of warfarin?",
    "Which blood pressure threshold starts antihypertensive treatment according to WHO?",
    "What is the maximum daily dose of metformin?",
]
TRANSCRIPT = [
    {"speaker": "doctor", "text": "What brings you in today?"},
    {"speaker": "patient", "text": "I have had a dry cough for two weeks and some tiredness."},
    {"speaker": "doctor", "text": "Any fever, chest pain or shortness of breath?"},
    {"speaker": "patient", "text": "No fever, no chest pain. A little short of breath on stairs."},
    {"speaker": "doctor", "text": "Your chest sounds clear. We will check a blood count."},
]


def traffic(settings: Settings) -> datetime:
    headers = {"Authorization": f"Bearer {issue_token('dr-demo', settings.auth_token_key)}"}
    patient = httpx.get(
        f"{settings.fhir_base_url}/Patient", params={"_count": "1"}, timeout=30
    ).json()["entry"][0]["resource"]
    started, stamp = datetime.now(UTC), int(time.time())
    with httpx.Client(base_url=API, headers=headers, timeout=600) as client:
        body = {"encounter_id": f"enc-trace-{stamp}", "patient_id": patient["id"]}
        draft = client.post("/v1/scribe/drafts", json={**body, "transcript": TRANSCRIPT})
        print("draft", draft.status_code, file=sys.stderr)
        if draft.status_code == 200:
            reject = {"decision": "reject", "reason": "tracing comparison"}
            client.post(f"/v1/drafts/{draft.json()['draft_id']}/review", json=reject)
        for n, question in enumerate(QUESTIONS):
            ask = {"encounter_id": f"ask-trace-{stamp}-{n}", "question": question}
            print("ask", client.post("/v1/ask", json=ask).status_code, file=sys.stderr)
    return started


def trace_ids(settings: Settings, since: datetime) -> list[tuple[str, str]]:
    with psycopg.connect(app_conninfo(settings)) as conn:
        rows = conn.execute(
            "SELECT action, trace_id FROM audit_log WHERE ts >= %s AND trace_id IS NOT NULL "
            "AND action IN ('draft.create', 'draft.reject', 'ask') ORDER BY seq",
            (since,),
        ).fetchall()
    return [(str(a), str(t)) for a, t in rows]


def file_spans(trace_id: str) -> list[dict[str, Any]]:
    spans = []
    for path in sorted(FILE_EXPORT.glob("traces*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if trace_id not in line:
                continue
            for rs in json.loads(line).get("resourceSpans", []):
                for ss in rs.get("scopeSpans", []):
                    spans += [s for s in ss.get("spans", []) if s.get("traceId") == trace_id]
    return spans


def phoenix_spans(trace_id: str) -> list[dict[str, Any]]:
    response = httpx.get(
        f"{PHOENIX}/v1/projects/default/spans",
        params={"trace_id": trace_id, "limit": 1000},
        timeout=60,
    )
    response.raise_for_status()
    data: list[dict[str, Any]] = response.json()["data"]
    return data


def langfuse_observations(settings: Settings, trace_id: str, since: datetime) -> int | str:
    auth = (
        settings.langfuse_public_key.get_secret_value(),
        settings.langfuse_secret_key.get_secret_value(),
    )
    params = {
        "traceId": trace_id,
        "limit": "100",
        "fromStartTime": (since - timedelta(minutes=5)).isoformat(),
        "toStartTime": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    }
    try:
        response = httpx.get(
            f"{settings.langfuse_host}/api/public/v2/observations",
            params=params,
            auth=auth,
            timeout=60,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return f"read failed ({type(exc).__name__})"
    return len(response.json().get("data", []))


def langfuse_ingestion(settings: Settings) -> str:
    """Probe the ingestion endpoint the collector uses (an empty batch)."""
    auth = (
        settings.langfuse_public_key.get_secret_value(),
        settings.langfuse_secret_key.get_secret_value(),
    )
    response = httpx.post(
        f"{settings.langfuse_host}/api/public/otel/v1/traces",
        content=b"",
        headers={"Content-Type": "application/x-protobuf"},
        auth=auth,
        timeout=60,
    )
    if response.status_code == 403 and "suspended" in response.text.lower():
        return "suspended by the free tier (HTTP 403)"
    return f"HTTP {response.status_code}"


def _docker(*args: str) -> str:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=False, encoding="utf-8"
    ).stdout.strip()


def _model_view(span: dict[str, Any], keys: tuple[str, ...]) -> str:
    attributes = span.get("attributes") or {}
    shown = [k for k in keys if attributes.get(k) not in (None, "")]
    return ", ".join(shown) or "none"


def main() -> int:
    settings = Settings()
    since = traffic(settings)
    time.sleep(30)  # the collector batches; Phoenix ingests asynchronously
    traces = trace_ids(settings, since)
    if not traces:
        print("no audit rows with trace ids: is the API rebuilt?", file=sys.stderr)
        return 1
    ingestion = langfuse_ingestion(settings)
    rows: list[tuple[str, str, int, int, int | str]] = []
    kinds: Counter[str] = Counter()
    gen_ai_keys: Counter[str] = Counter()
    openinference_keys: Counter[str] = Counter()
    for action, trace_id in traces:
        local, phoenix = file_spans(trace_id), phoenix_spans(trace_id)
        rows.append(
            (
                action,
                trace_id[:12],
                len(local),
                len(phoenix),
                langfuse_observations(settings, trace_id, since),
            )
        )
        for span in phoenix:
            kinds[span.get("span_kind") or "?"] += 1
            if str(span.get("name", "")).startswith("chat "):
                gen_ai_keys[
                    _model_view(
                        span,
                        (
                            "gen_ai.request.model",
                            "gen_ai.response.model",
                            "gen_ai.usage.input_tokens",
                            "gen_ai.usage.output_tokens",
                        ),
                    )
                ] += 1
                openinference_keys[
                    _model_view(
                        span,
                        (
                            "llm.model_name",
                            "llm.token_count.prompt",
                            "llm.token_count.completion",
                            "openinference.span.kind",
                        ),
                    )
                ] += 1
    memory = _docker("stats", "--no-stream", "--format", "{{.MemUsage}}", "clinscribe-phoenix-1")
    disk = _docker(  # no du in the image: Phoenix runs on Python
        "exec",
        "clinscribe-phoenix-1",
        "python",
        "-c",
        "import os; print(sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in "
        "os.walk('/data') for f in fs) // 1024, 'KiB')",
    )
    image = _docker("image", "ls", "--format", "{{.Size}}", "arizephoenix/phoenix:20.21.1")
    total_local = sum(r[2] for r in rows)
    total_phoenix = sum(r[3] for r in rows)
    lines = [
        "# Tracing backends on the same traffic (ADR-0024)",
        "",
        f"Generated by `evals/llmops/tracing_compare.py` on {since:%Y-%m-%d %H:%M} UTC: one",
        "synthetic consultation through the API with the real models (a Scribe draft, rejected,",
        "and three Ask questions). The collector sends the same redacted spans to its local file,",
        "to Langfuse Cloud and to Phoenix (`just phoenix on`). Trace ids from the audit rows.",
        "",
        f"- spans in the local file export: {total_local}; in Phoenix: {total_phoenix}",
        f"- Langfuse Cloud ingestion: {ingestion}",
        f"- Phoenix: image {image}, memory {memory}, data on disk {disk or '?'}",
        "",
        "| request | trace | spans, file | spans, Phoenix | observations, Langfuse |",
        "|---|---|---|---|---|",
        *[f"| {a} | `{t}` | {f} | {p} | {lf} |" for a, t, f, p, lf in rows],
        "",
        "Phoenix span kinds (OpenInference; set from the span's attributes):",
        "",
        *[f"- {k}: {n}" for k, n in kinds.most_common()],
        "",
        "Model-call spans (`chat <alias>`) in Phoenix: which attributes it holds",
        "",
        "| OpenTelemetry GenAI attributes present | spans |",
        "|---|---|",
        *[f"| {k} | {n} |" for k, n in gen_ai_keys.most_common()],
        "",
        "| OpenInference attributes present (Phoenix's model and token columns) | spans |",
        "|---|---|",
        *[f"| {k} | {n} |" for k, n in openinference_keys.most_common()],
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
