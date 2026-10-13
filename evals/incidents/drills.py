"""Incident drills (Phase 6; SPEC section 7): inject a fault, measure, restore.

  uv run python -m evals.incidents.drills outage    primary model down during real Ask traffic
  uv run python -m evals.incidents.drills latency   +1,500 ms in guideline search under load

outage: `chaos primary-down` on, 4 agentic questions through the API (their grading step uses the
primary alias, so it must fail over), then the gateway's spend log for the window shows which
deployment served each call. latency: CHAOS_SEARCH_DELAY_MS on guidelines-mcp, 10 sessions with the
mock model (as the load test), then the tool spans in the local trace export locate the slow step.
Both restore the normal configuration in `finally`. Output: evals/reports/incidents/<drill>.md.
"""

import asyncio
import json
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import httpx

from apps.api.auth import issue_token
from config.settings import Settings
from evals.load.load_test import level, recreate_api
from evals.rag.metrics import percentile
from scripts.chaos import set_fault

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "evals" / "reports" / "incidents"
API = "http://127.0.0.1:8000"
QUESTIONS = [
    "Does clarithromycin interact with warfarin?",
    "Apixaban versus warfarin for stroke prevention in atrial fibrillation?",
    "Can a patient on metformin take contrast dye together with it?",
    "Which is safer in pregnancy, labetalol or nifedipine?",
]


def spend_log(since: datetime) -> Counter[str]:
    password = Settings().litellm_db_password.get_secret_value()
    # the timestamp travels as a psql variable (quoted by psql), not pasted into the SQL text
    query = (
        "SELECT model_group || ' <- ' || model FROM \"LiteLLM_SpendLogs\" "
        "WHERE \"startTime\" >= :'since';\n"
    )
    out = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "-e",
            "PGPASSWORD",
            "postgres",
            "psql",
            "-h",
            "127.0.0.1",
            "-U",
            "litellm",
            "-d",
            "litellm",
            "-At",
            "-v",
            f"since={since.strftime('%Y-%m-%d %H:%M:%S')}",
        ],
        input=query,
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
        env={**os.environ, "PGPASSWORD": password},
    ).stdout
    return Counter(line for line in out.splitlines() if line.strip())


def outage() -> str:
    token = issue_token("dr-demo", Settings().auth_token_key)
    time.sleep(2)
    since = datetime.now(UTC).replace(tzinfo=None)
    results = []
    set_fault("primary-down", on=True)
    try:
        for question in QUESTIONS:
            started = time.perf_counter()
            response = httpx.post(
                f"{API}/v1/ask",
                json={"encounter_id": "drill-outage", "question": question},
                headers={"Authorization": f"Bearer {token}"},
                timeout=600,
            )
            body = response.json() if response.status_code == 200 else {}
            results.append(
                (
                    question,
                    response.status_code,
                    time.perf_counter() - started,
                    body.get("route"),
                    (body.get("answer") or {}).get("abstained"),
                )
            )
    finally:
        set_fault("primary-down", on=False)
    time.sleep(70)  # LiteLLM writes spend logs in batches
    served = spend_log(since)
    lines = [
        "# Drill: primary provider outage",
        "",
        f"`chaos primary-down` on at {since:%Y-%m-%d %H:%M} UTC; {len(QUESTIONS)} agentic Ask "
        "questions "
        "through the API; then off.",
        "",
        "| question | status | seconds | route | abstained |",
        "|---|---|---|---|---|",
        *[f"| {q} | {s} | {t:.1f} | {r} | {a} |" for q, s, t, r, a in results],
        "",
        "Gateway spend log for the window (alias <- deployment that served it):",
        "",
        "| alias <- deployment | calls |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in served.most_common()],
    ]
    return "\n".join(lines)


def tool_spans(since: float) -> dict[str, list[float]]:
    spans: dict[str, list[float]] = defaultdict(list)
    for line in (ROOT / ".artifacts" / "otel" / "traces.jsonl").open(encoding="utf-8"):
        for rs in json.loads(line).get("resourceSpans", []):
            for ss in rs.get("scopeSpans", []):
                for sp in ss.get("spans", []):
                    start = int(sp["startTimeUnixNano"]) / 1e9
                    if start >= since:
                        spans[sp["name"]].append((int(sp["endTimeUnixNano"]) / 1e9 - start) * 1000)
    return spans


def latency() -> str:
    token = issue_token("dr-demo", Settings().auth_token_key)
    from evals.golden.golden import load_items

    pool = [i.question for i in load_items() if i.answerable]
    import random

    rows = {}
    recreate_api(load_mode=True)
    try:
        for label, delay in (("normal", ""), ("delay 1500 ms", "1500")):
            env = {**os.environ, "CHAOS_SEARCH_DELAY_MS": delay}
            subprocess.run(
                [
                    "docker",
                    "compose",
                    "--profile",
                    "core",
                    "--profile",
                    "fhir",
                    "--profile",
                    "rag",
                    "up",
                    "-d",
                    "--force-recreate",
                    "--no-deps",
                    "--wait",
                    "guidelines-mcp",
                ],
                check=True,
                env=env,
                cwd=ROOT,
                capture_output=True,
            )
            asyncio.run(level(2, token, pool, random.Random(1)))  # warm-up
            since = time.time()
            result = asyncio.run(level(10, token, pool, random.Random(7)))
            time.sleep(10)  # span export batch
            search = tool_spans(since).get("mcp search_guidelines", [])
            rows[label] = (result, search)
    finally:
        subprocess.run(
            [
                "docker",
                "compose",
                "--profile",
                "core",
                "--profile",
                "fhir",
                "--profile",
                "rag",
                "up",
                "-d",
                "--force-recreate",
                "--no-deps",
                "--wait",
                "guidelines-mcp",
            ],
            check=True,
            env={**os.environ, "CHAOS_SEARCH_DELAY_MS": ""},
            cwd=ROOT,
            capture_output=True,
        )
        recreate_api(load_mode=False)
    lines = [
        "# Drill: latency spike in a dependency",
        "",
        "10 concurrent sessions (3 questions each, mock model), without and with",
        "`CHAOS_SEARCH_DELAY_MS=1500` on guidelines-mcp. The SPEC drill injects the delay",
        "into TTS;"
        "voice is not built yet, so the delay goes into guideline search, which every Ask calls.",
        "",
        "| run | Ask p50 ms | Ask p95 ms | errors | `mcp search_guidelines` span p50 / p95 ms |",
        "|---|---|---|---|---|",
    ]
    for label, (result, search) in rows.items():
        span = (
            f"{percentile(search, 0.5):.0f} / {percentile(search, 0.95):.0f}"
            if search
            else "no spans"
        )
        lines.append(
            f"| {label} | {result['p50']:.0f} | {result['p95']:.0f} | "
            f"{result['errors']:.0f} | {span} |"
        )
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    drills = {"outage": outage, "latency": latency}
    if not argv or argv[0] not in drills:
        print(f"usage: drills {'|'.join(drills)}")
        return 2
    report = drills[argv[0]]()
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"{argv[0]}.md").write_text(report + "\n", encoding="utf-8", newline="\n")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
