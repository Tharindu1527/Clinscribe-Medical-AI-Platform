"""Gateway latency with the primary up vs down, p50/p95 (PROGRESS task 12).

Usage: uv run python -m evals.llmops.failover_latency   (needs `just up`; ~40 real LLM calls)
Writes evals/reports/llmops/failover_latency.md and .json. Every turn must succeed in both modes.
Latency is client-side wall time through the gateway, so the down mode includes the failed
primary attempt plus the fallback.
"""

import json
import statistics
import sys
import time
from pathlib import Path

from config.settings import Settings
from llmops.gateway.client import ChatMessage, GatewayClient
from privacy.deid.types import issue
from scripts.chaos import set_fault

REPORT_DIR = Path(__file__).resolve().parents[1] / "reports" / "llmops"
CALLS = 20
PACE_S = 3.0
PROMPT = [
    ChatMessage(
        "user",
        issue("Reply with one short sentence about hand washing.", source="synthetic-test-fixture"),
    )
]


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(q * (len(ordered) - 1))))
    return ordered[index]


def measure(client: GatewayClient) -> tuple[list[float], dict[str, int], int]:
    latencies: list[float] = []
    served: dict[str, int] = {}
    failures = 0
    for _ in range(CALLS):
        try:
            result = client.complete("clinscribe-default", PROMPT, max_tokens=256)
            latencies.append(result.latency_ms)
            served[result.model] = served.get(result.model, 0) + 1
        except Exception:  # noqa: BLE001 - every failure counts against the gate
            failures += 1
        time.sleep(PACE_S)
    return latencies, served, failures


def main() -> int:
    settings = Settings()
    client = GatewayClient(settings.gateway_url, settings.litellm_app_key)
    results = {}
    try:
        results["primary up"] = measure(client)
        set_fault("primary-down", on=True)
        try:
            results["primary down"] = measure(client)
        finally:
            set_fault("primary-down", on=False)
    finally:
        client.close()

    rows, summary = [], {}
    for mode, (latencies, served, failures) in results.items():
        p50 = percentile(latencies, 0.50) if latencies else float("nan")
        p95 = percentile(latencies, 0.95) if latencies else float("nan")
        summary[mode] = {
            "calls": CALLS,
            "succeeded": len(latencies),
            "failed": failures,
            "p50_ms": round(p50),
            "p95_ms": round(p95),
            "mean_ms": round(statistics.mean(latencies)) if latencies else None,
            "served_by": served,
        }
        served_text = ", ".join(f"{k} x{v}" for k, v in served.items())
        rows.append(
            f"| {mode} | {len(latencies)}/{CALLS} | {p50:,.0f} | {p95:,.0f} | {served_text} |"
        )
    passed = all(s["failed"] == 0 for s in summary.values())

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "failover_latency.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Gateway latency: primary up vs down",
        "",
        f"{CALLS} calls per mode to `clinscribe-default`, max_tokens 256, "
        f"paced {PACE_S:.0f} s apart.",
        "Client-side wall time through the LiteLLM gateway (free tiers; network to providers "
        "included).",
        "",
        "| Mode | Succeeded | p50 ms | p95 ms | Served by |",
        "|---|---|---|---|---|",
        *rows,
        "",
        f"Every turn succeeded in both modes: **{'PASS' if passed else 'FAIL'}**",
    ]
    (REPORT_DIR / "failover_latency.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
