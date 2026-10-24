"""PHI leak test (PROGRESS task 10, Phase 1 gate b): seeded fake PHI must not appear in any sink.

Usage: uv run python -m evals.privacy.leak_test     (needs `just up`; makes ~20 real LLM calls)
Writes evals/reports/privacy/leak_test.md and .json; exits 1 unless 0 leaks and the positive
control finds every seed value.

Sinks scanned: collector file export, `docker compose logs` of every service, Langfuse (v2
observations API), LiteLLM spend logs, the audit table and the de-ID mapping table.
Also reported (not part of gate b): seed values that survived de-ID in the text the LLM saw.
All PHI here is synthetic (Faker, seed 1234). The report names entity types, never values.
"""

import json
import os
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import psycopg

from config.db import app_conninfo
from config.settings import Settings
from evals.privacy.corpus import NER, build

API = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parents[2]
FILE_EXPORT = ROOT / ".artifacts" / "otel" / "traces.jsonl"
REPORT_DIR = ROOT / "evals" / "reports" / "privacy"
N_TRANSCRIPTS = 20
SEED = 1234
PACE_S = 4.0  # stay well under free-tier rate limits


@dataclass(frozen=True)
class Seed:
    entity: str
    value: str


def patterns_for(seed: Seed) -> list[re.Pattern[str]]:
    """How a leaked value could look in a sink: verbatim, or (for long numbers) digits only."""
    if seed.entity == "AGE_OVER_89":
        # A bare "100" is everywhere (token counts, ports); an age leaks with its context
        age = re.escape(seed.value)
        return [
            re.compile(rf"(?<!\d){age}\s*-?\s*(?:years?|yrs?|y/?o)\b", re.IGNORECASE),
            re.compile(rf"\bage[ds]?\s*:?\s*{age}(?!\d)", re.IGNORECASE),
        ]
    # verbatim, but not as part of a longer word or number ("02115" inside "9021150")
    found = [re.compile(rf"(?<![A-Za-z0-9]){re.escape(seed.value)}(?![A-Za-z0-9])", re.IGNORECASE)]
    if seed.entity in NER:
        # each name/place word, case-sensitive and whole-word, so JSON keys do not match
        found += [
            re.compile(rf"\b{re.escape(w)}\b") for w in re.findall(r"[A-Za-z]{3,}", seed.value)
        ]
    digits = re.sub(r"\D", "", seed.value)
    if len(digits) >= 7 and digits != seed.value:
        found.append(re.compile(rf"(?<!\d){digits}(?!\d)"))
    return found


def scan(text: str, seeds: list[Seed]) -> list[Seed]:
    return [s for s in seeds if any(p.search(text) for p in patterns_for(s))]


def _run(cmd: list[str], env: dict[str, str] | None = None, stdin: str | None = None) -> str:
    out = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env, input=stdin)
    return out.stdout + out.stderr


def collect_sinks(
    settings: Settings, started: datetime, trace_ids: list[str], encounters: list[str]
) -> dict[str, str]:
    sinks: dict[str, str] = {}

    lines = FILE_EXPORT.read_text(encoding="utf-8").splitlines() if FILE_EXPORT.exists() else []
    sinks["collector file export"] = "\n".join(
        ln for ln in lines if any(t in ln for t in trace_ids)
    )

    sinks["docker compose logs"] = _run(
        [
            "docker",
            "compose",
            "--profile",
            "*",
            "logs",
            "--no-color",
            "--since",
            started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        ]
    )

    auth = (
        settings.langfuse_public_key.get_secret_value(),
        settings.langfuse_secret_key.get_secret_value(),
    )
    bodies = []
    for trace_id in trace_ids:
        params = {
            "traceId": trace_id,
            "limit": "100",
            "fromStartTime": (started - timedelta(minutes=5)).isoformat(),
            "toStartTime": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        }
        response = httpx.get(
            f"{settings.langfuse_host}/api/public/v2/observations",
            params=params,
            auth=auth,
            timeout=60,
        )
        response.raise_for_status()
        bodies.append(response.text)
    sinks["Langfuse observations"] = "\n".join(bodies)

    sql = (
        'SELECT row_to_json(s)::text FROM "LiteLLM_SpendLogs" s WHERE "startTime" >= :\'since\';\n'
    )
    sinks["LiteLLM spend logs"] = _run(
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
            "localhost",
            "-U",
            "litellm",
            "-d",
            "litellm",
            "-At",
            "-v",
            f"since={(started - timedelta(minutes=1)).isoformat()}",
        ],
        env={**os.environ, "PGPASSWORD": settings.litellm_db_password.get_secret_value()},
        stdin=sql,
    )

    with psycopg.connect(app_conninfo(settings)) as conn:
        audit = conn.execute(
            "SELECT row_to_json(a)::text FROM audit_log a WHERE encounter_id = ANY(%s)",
            (encounters,),
        ).fetchall()
        mappings = conn.execute(
            "SELECT encounter_id, entity_type, surrogate, encode(ciphertext, 'escape'),"
            " encode(lookup_hash, 'hex') FROM deid_mappings WHERE encounter_id = ANY(%s)",
            (encounters,),
        ).fetchall()
    sinks["audit table"] = "\n".join(r[0] for r in audit)
    sinks["de-ID mapping table"] = "\n".join(" ".join(map(str, r)) for r in mappings)
    return sinks


def main() -> int:
    settings = Settings()
    run = uuid.uuid4().hex[:8]
    transcripts = build(n=N_TRANSCRIPTS, seed=SEED)
    seeds = [Seed(e, v) for t in transcripts for (e, v) in t.phi]
    started = datetime.now(UTC)

    trace_ids, encounters, llm_exposed = [], [], []
    for i, transcript in enumerate(transcripts):
        encounter = f"leak-{run}-{i:02d}"
        encounters.append(encounter)
        response = httpx.post(
            f"{API}/v1/dev/complete",
            timeout=180,
            json={"encounter_id": encounter, "text": transcript.text},
            headers={"X-Actor": "leak-test"},
        )
        response.raise_for_status()
        trace_ids.append(response.json()["trace_id"])
        # Same encounter -> same surrogates: this is exactly the text the LLM received
        seen = httpx.post(
            f"{settings.deid_url}/deidentify",
            timeout=60,
            json={"encounter_id": encounter, "text": transcript.text},
        ).json()["text"]
        llm_exposed += [Seed(e, v) for (e, v) in transcript.phi if scan(seen, [Seed(e, v)])]
        time.sleep(PACE_S)

    time.sleep(60)  # let the collector, Langfuse ingestion and LiteLLM's batched spend logs land
    sinks = collect_sinks(settings, started, trace_ids, encounters)
    leaks = {name: scan(text, seeds) for name, text in sinks.items()}
    sink_sizes = {name: len(text) for name, text in sinks.items()}

    planted = json.dumps(
        {
            "note": "positive control: every seed value as it would appear if leaked",
            "values": [
                f"a {s.value}-year-old" if s.entity == "AGE_OVER_89" else s.value for s in seeds
            ],
        }
    )
    control_found = len(scan(planted, seeds)) / len(seeds)
    total_leaks = sum(len(v) for v in leaks.values())
    passed = total_leaks == 0 and control_found == 1.0 and all(sink_sizes.values())

    by_type: dict[str, int] = {}
    for s in llm_exposed:
        by_type[s.entity] = by_type.get(s.entity, 0) + 1
    summary = {
        "run": run,
        "transcripts": N_TRANSCRIPTS,
        "seed_values": len(seeds),
        "faker_seed": SEED,
        "leaks_per_sink": {k: len(v) for k, v in leaks.items()},
        "leaked_types_per_sink": {k: sorted({s.entity for s in v}) for k, v in leaks.items()},
        "sink_bytes_scanned": sink_sizes,
        "positive_control_recall": control_found,
        "llm_exposed_seed_values": len(llm_exposed),
        "llm_exposed_by_type": by_type,
        "gate_passed": passed,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "leak_test.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    rows = []
    for name, found in leaks.items():
        types = ", ".join(sorted({s.entity for s in found})) or "-"
        rows.append(f"| {name} | {sink_sizes[name]:,} | {len(found)} | {types} |")
    exposed = ", ".join(f"{k} {v}" for k, v in sorted(by_type.items())) or "none"
    lines = [
        "# PHI leak test (Phase 1 gate b)",
        "",
        f"Run `{run}`: {N_TRANSCRIPTS} synthetic transcripts, {len(seeds)} seeded fake PHI "
        f"values (Faker seed {SEED}), sent through `POST /v1/dev/complete`.",
        "",
        "| Sink | Bytes scanned | Leaked values | Leaked types |",
        "|---|---|---|---|",
        *rows,
        "",
        f"Positive control (scanner finds planted seed values): **{control_found:.0%}**",
        "",
        "Gate b (0 leaks in traces and logs, control 100%, every sink non-empty): "
        f"**{'PASS' if passed else 'FAIL'}**",
        "",
        "## Not part of gate b: what the LLM saw",
        "",
        "Seed values that survived de-ID in the text sent to the gateway: "
        f"**{len(llm_exposed)} of {len(seeds)}** ({exposed}).",
        "Structured identifiers are covered by regex recognisers; names and places depend on",
        f"the name/place recogniser (`DEID_NER={settings.deid_ner}` in `.env`; "
        "ADR-0004, ADR-0014).",
    ]
    (REPORT_DIR / "leak_test.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
