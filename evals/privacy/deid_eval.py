"""De-ID recall per Safe Harbor type on the seeded synthetic corpus (PROGRESS task 6 gate).

Usage: uv run python -m evals.privacy.deid_eval
Writes evals/reports/privacy/deid_v0.md and .json. Exits 1 if any structured type has recall < 1.0.
A PHI value counts as caught only if no trace of it survives in the output:
  structured values: their letters/digits do not appear in the output's letters/digits;
  names/places: none of their words (3+ letters) appear as a whole word.
"""

import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

from cryptography.fernet import Fernet
from pydantic import SecretStr

from config.settings import Settings
from evals.privacy.corpus import NER, STRUCTURED, TEMPLATES, build
from privacy.deid.engine import SURROGATE_RE, Deidentifier, build_analyzer
from privacy.deid.store import InMemoryStore, normalise

REPORT_DIR = Path(__file__).resolve().parents[1] / "reports" / "privacy"


def leaked(entity: str, value: str, output: str) -> bool:
    # Surrogate labels contain digits ("AGE_OVER_89_1" holds "91"), so drop them before checking
    output = SURROGATE_RE.sub(" ", output)
    if entity in NER:
        words = [w for w in re.findall(r"[A-Za-z]{3,}", value)]
        return any(re.search(rf"\b{re.escape(w)}\b", output, re.IGNORECASE) for w in words)
    return normalise(value) in normalise(output)


def main() -> int:
    settings = Settings()
    corpus = build()
    deidentifier = Deidentifier(
        build_analyzer(settings.deid_spacy_model),
        InMemoryStore(
            SecretStr(Fernet.generate_key().decode())
        ),  # throwaway key; nothing persisted
    )
    totals: Counter[str] = Counter()
    caught: Counter[str] = Counter()
    examples: dict[str, str] = {}
    started = time.perf_counter()
    latencies = []
    for i, snippet in enumerate(corpus):
        t0 = time.perf_counter()
        output = deidentifier.deidentify(snippet.text, encounter_id=f"eval-{i}").text.text
        latencies.append((time.perf_counter() - t0) * 1000)
        for entity, value in snippet.phi:
            totals[entity] += 1
            if leaked(entity, value, output):
                examples.setdefault(
                    entity, f"{entity}: first miss in template {i % len(TEMPLATES)}"
                )
            else:
                caught[entity] += 1
    elapsed = time.perf_counter() - started
    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[int(len(latencies) * 0.95) - 1]

    rows = []
    failed = []
    for entity in (*STRUCTURED, *NER):
        if not totals[entity]:
            continue
        recall = caught[entity] / totals[entity]
        kind = "structured (gate 1.0)" if entity in STRUCTURED else "NER (baseline)"
        rows.append(
            {"entity": entity, "kind": kind, "n": totals[entity], "recall": round(recall, 3)}
        )
        if entity in STRUCTURED and recall < 1.0:
            failed.append(entity)

    verdict = "PASS" if not failed else "FAIL: " + ", ".join(failed)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    summary = {
        "spacy_model": settings.deid_spacy_model,
        "snippets": len(corpus),
        "seed": 42,
        "latency_ms_p50": round(p50, 1),
        "latency_ms_p95": round(p95, 1),
        "results": rows,
        "gate_passed": not failed,
    }
    (REPORT_DIR / "deid_v0.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# De-ID v0 recall (synthetic corpus)",
        "",
        f"Model `{settings.deid_spacy_model}`, {len(corpus)} seeded snippets (Faker seed 42), "
        f"{elapsed:.1f} s total; per snippet p50 {p50:.1f} ms, p95 {p95:.1f} ms (in-process).",
        "",
        "| Entity | Kind | N | Recall |",
        "|---|---|---|---|",
        *[f"| {r['entity']} | {r['kind']} | {r['n']} | {r['recall']:.3f} |" for r in rows],
        "",
        f"Gate (structured recall = 1.0): **{verdict}**",
        "",
        "Missed types (no PHI values are written to this report):",
        *(f"- {msg}" for msg in examples.values()),
        "",
        "Limits: template-based synthetic text, not real dictation; names and places depend on",
        "spaCy NER and are the baseline for the Phase 5 LoRA fine-tuned model.",
    ]
    (REPORT_DIR / "deid_v0.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
