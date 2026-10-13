"""Load test of the Ask endpoint at 10, 50 and 100 concurrent sessions (Phase 6; SPEC section 11).

Free tiers cannot serve this load, so for the run the API is recreated with
CLINSCRIBE_MODEL_OVERRIDE=clinscribe-mock (a canned cited answer from the gateway, no provider call)
and the mock-only `clinscribe-load` gateway key; everything else is real: auth, de-ID, the agent
graph (router, guardrails), guidelines-mcp retrieval (encoders + BM25 + ColBERT on CPU),
druggraph-mcp, the gateway and the audit log. The API is restored afterwards.

Each session signs in as the demo doctor and sends REQUESTS questions one after another (golden
questions, seeded). Reported per level: requests, errors, p50 / p95 / max latency, throughput.

  uv run python -m evals.load.load_test      (needs `just up rag`; ~10 minutes)
"""

import asyncio
import os
import random
import subprocess
import sys
import time
from pathlib import Path

import httpx

from apps.api.auth import issue_token
from config.settings import Settings
from evals.golden.golden import load_items
from evals.rag.metrics import percentile
from scripts import gateway_keys

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "evals" / "reports" / "load" / "load_test.md"
API = "http://127.0.0.1:8000"
LEVELS = (10, 50, 100)
REQUESTS = 3
SEED = 6


def recreate_api(load_mode: bool) -> None:
    env = dict(os.environ)
    if load_mode:
        env["CLINSCRIBE_MODEL_OVERRIDE"] = "clinscribe-mock"
        env["LITELLM_APP_KEY_OVERRIDE"] = Settings().litellm_load_key.get_secret_value()
    else:
        env.pop("CLINSCRIBE_MODEL_OVERRIDE", None)
        env.pop("LITELLM_APP_KEY_OVERRIDE", None)
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
            "api",
        ],
        check=True,
        env=env,
        cwd=ROOT,
        capture_output=True,
    )


async def session(
    client: httpx.AsyncClient, token: str, questions: list[str], out: list[tuple[float, int]]
) -> None:
    for question in questions:
        started = time.perf_counter()
        try:
            response = await client.post(
                f"{API}/v1/ask",
                json={"encounter_id": "load-test", "question": question},
                headers={"Authorization": f"Bearer {token}"},
            )
            status = response.status_code
        except httpx.HTTPError:
            status = 0
        out.append(((time.perf_counter() - started) * 1000, status))


async def level(
    concurrency: int, token: str, pool: list[str], rng: random.Random
) -> dict[str, float]:
    results: list[tuple[float, int]] = []
    limits = httpx.Limits(max_connections=concurrency + 10, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(timeout=600, limits=limits) as client:
        started = time.perf_counter()
        await asyncio.gather(
            *[
                session(client, token, rng.sample(pool, REQUESTS), results)
                for _ in range(concurrency)
            ]
        )
        wall = time.perf_counter() - started
    ok = [ms for ms, status in results if status == 200]
    return {
        "sessions": concurrency,
        "requests": len(results),
        "errors": len(results) - len(ok),
        "p50": percentile(ok, 0.5) if ok else float("nan"),
        "p95": percentile(ok, 0.95) if ok else float("nan"),
        "max": max(ok) if ok else float("nan"),
        "rps": len(ok) / wall,
        "wall": wall,
    }


def main() -> int:
    if gateway_keys.main() != 0:
        return 1
    rng = random.Random(SEED)
    pool = [i.question for i in load_items() if i.answerable]
    token = issue_token("dr-demo", Settings().auth_token_key)
    rows = []
    recreate_api(load_mode=True)
    try:
        asyncio.run(level(2, token, pool, rng))  # warm-up (model loads, connection pools)
        for concurrency in LEVELS:
            rows.append(asyncio.run(level(concurrency, token, pool, rng)))
            r = rows[-1]
            print(
                f"{concurrency} sessions: p50 {r['p50']:.0f} ms, p95 {r['p95']:.0f} ms, "
                f"errors {r['errors']}/{r['requests']}, {r['rps']:.2f} req/s"
            )
    finally:
        recreate_api(load_mode=False)
    lines = [
        "# Load test: Ask endpoint (Phase 6)",
        "",
        f"{REQUESTS} questions per session, sent one after another; sessions run concurrently.",
        "The model is the gateway's canned `clinscribe-mock` alias (no provider call), so the",
        "numbers measure ClinScribe itself: auth, de-ID, the agent graph, guidelines-mcp retrieval",
        "(CPU), druggraph-mcp, the gateway and the audit log, on one laptop (12 logical CPUs,",
        "WSL2 10 GB). Latency is per request, client side, successful requests only.",
        "",
        "| sessions | requests | errors | p50 ms | p95 ms | max ms | throughput req/s |",
        "|---|---|---|---|---|---|---|",
        *[
            f"| {r['sessions']} | {r['requests']} | {r['errors']} | {r['p50']:.0f} | "
            f"{r['p95']:.0f} | {r['max']:.0f} | {r['rps']:.2f} |"
            for r in rows
        ],
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(REPORT.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
