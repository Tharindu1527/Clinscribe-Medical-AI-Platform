"""De-ID evaluation: recall per Safe Harbor type and over-redaction (de-ID v1).

Usage: uv run python -m evals.privacy.deid_eval
Writes evals/reports/privacy/deid_v1_<spacy model>.md and .json (deid_v0.* is the Phase 1 baseline).
Gates: structured recall 1.0, PERSON >= 0.99, LOCATION >= 0.98, over-redaction <= 1% of PHI-free
clinical sentences. Exit 1 if any gate fails.

A PHI value counts as caught only if no trace of it survives in the output:
  structured values: their letters/digits do not appear in the output's letters/digits;
  names/places: none of their words (3+ letters; titles and degrees excluded) appear as a word.
Limits: the seeded corpus is template-based and Faker draws names from US Census-style lists, so
recall here is optimistic; real dictation (Phase 2 transcripts) is the harder test.
"""

import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
from pydantic import SecretStr

from config.settings import Settings
from evals.privacy.clinical_negatives import SENTENCES
from evals.privacy.corpus import HELDOUT_TEMPLATES, NER, STRUCTURED, TEMPLATES, build
from privacy.deid.engine import SURROGATE_RE, Deidentifier, analyzer_for
from privacy.deid.store import InMemoryStore, normalise

REPORT_DIR = Path(__file__).resolve().parents[1] / "reports" / "privacy"
# one report per name/place recogniser: deid_v1_en_core_web_md (spaCy), deid_v2_tagger (ADR-0014)
REPORT_PREFIX = "deid_v1"
RECALL_GATES = {"PERSON": 0.99, "LOCATION": 0.98, **{t: 1.0 for t in STRUCTURED}}
MAX_OVER_REDACTION = 0.01
# Honorifics and degrees are not identifiers: "Mrs. PERSON_1" or "PERSON_1 DVM" is not a leak
NOT_IDENTIFYING = {
    "mr",
    "mrs",
    "ms",
    "miss",
    "dr",
    "prof",
    "jr",
    "sr",
    "md",
    "dds",
    "dvm",
    "phd",
    "rn",
}


def leaked(entity: str, value: str, output: str) -> bool:
    # Surrogate labels contain digits ("AGE_OVER_89_1" holds "91"), so drop them before checking
    output = SURROGATE_RE.sub(" ", output)
    if entity in NER:
        words = [w for w in re.findall(r"[A-Za-z]{3,}", value) if w.lower() not in NOT_IDENTIFYING]
        return any(re.search(rf"\b{re.escape(w)}\b", output, re.IGNORECASE) for w in words)
    return normalise(value) in normalise(output)


def deidentifier_for(ner: str, spacy_model: str, tagger_path: str = "") -> Deidentifier:
    return Deidentifier(
        analyzer_for(ner, spacy_model, tagger_path),
        InMemoryStore(SecretStr(Fernet.generate_key().decode())),  # throwaway; nothing persisted
    )


def main() -> int:
    settings = Settings()
    model = settings.deid_spacy_model
    deidentifier = deidentifier_for(
        settings.deid_ner, settings.deid_spacy_model, settings.deid_tagger_path
    )
    summary, over, elapsed = evaluate(deidentifier)
    summary = {"spacy_model": model, "ner": settings.deid_ner, **summary}
    failed = summary["failed"]
    p50, p95 = summary["latency_ms_p50"], summary["latency_ms_p95"]
    corpus_size, rows = summary["snippets"], summary["results"]
    held_rows = summary["heldout"]
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    name = "deid_v2_tagger" if settings.deid_ner == "tagger" else f"{REPORT_PREFIX}_{model}"
    (REPORT_DIR / f"{name}.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    lines = [
        f"# De-ID ({settings.deid_ner}): recall and over-redaction (synthetic data)",
        "",
        f"Names/places: `{settings.deid_ner}` (tokens: `{model}`); {corpus_size} seeded snippets "
        "(Faker seed 42), "
        f"{elapsed:.1f} s; per snippet p50 {p50:.1f} ms, p95 {p95:.1f} ms (in-process).",
        "",
        "| Entity | N | Recall | Gate |",
        "|---|---|---|---|",
        *[f"| {r['entity']} | {r['n']} | {r['recall']:.3f} | {r['gate']} |" for r in rows],
        "",
        f"Over-redaction: **{len(over)} of {len(SENTENCES)}** PHI-free clinical sentences altered "
        f"({summary['over_redaction_rate']:.1%}; gate {MAX_OVER_REDACTION:.0%}).",
        *[f"- #{i} ({types}): {text}" for i, types, text in over],
        "",
        f"Misses by template (entity@template: count): {summary['misses_by_template'] or 'none'}",
        "",
        "## Held out (no gate): new phrasings and seed, not used to design the recognisers",
        "",
        "| Entity | N | Recall |",
        "|---|---|---|",
        *[f"| {r['entity']} | {r['n']} | {r['recall']:.3f} |" for r in held_rows],
        "",
        f"Held-out misses (entity@template: count): "
        f"{summary['heldout_misses_by_template'] or 'none'}",
        "",
        f"Gate: **{'PASS' if not failed else 'FAIL: ' + '; '.join(failed)}**",
        "",
        "Limits: template-based synthetic text; Faker draws names from US Census-style lists, so",
        "recall is optimistic. Real dictation (Phase 2 transcripts) is the harder test.",
    ]
    (REPORT_DIR / f"{name}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 1 if failed else 0


def evaluate(deidentifier: Any) -> tuple[dict[str, Any], list[tuple[int, str, str]], float]:
    """Recall per type, over-redaction and the held-out set for one de-identifier, with the
    gates applied; nothing is written (CI runs this, tests/unit/test_quality_gates.py)."""
    corpus = build()
    totals: Counter[str] = Counter()
    caught: Counter[str] = Counter()
    misses: Counter[tuple[str, int]] = Counter()
    latencies = []
    started = time.perf_counter()
    for i, snippet in enumerate(corpus):
        t0 = time.perf_counter()
        output = deidentifier.deidentify(snippet.text, encounter_id=f"eval-{i}").text.text
        latencies.append((time.perf_counter() - t0) * 1000)
        for entity, value in snippet.phi:
            totals[entity] += 1
            if leaked(entity, value, output):
                misses[(entity, i % len(TEMPLATES))] += 1
            else:
                caught[entity] += 1
    elapsed = time.perf_counter() - started
    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[int(len(latencies) * 0.95) - 1]

    # Over-redaction: any replacement in a PHI-free clinical sentence damages its meaning
    over: list[tuple[int, str, str]] = []
    for i, sentence in enumerate(SENTENCES):
        result = deidentifier.deidentify(sentence, encounter_id=f"neg-{i}")
        if result.replacements:
            types = ", ".join(sorted({r.entity for r in result.replacements}))
            over.append((i, types, result.text.text))
    over_rate = len(over) / len(SENTENCES)

    # Held-out phrasings and seed: generalisation, reported without a gate
    held_totals: Counter[str] = Counter()
    held_caught: Counter[str] = Counter()
    held_misses: Counter[tuple[str, int]] = Counter()
    for i, snippet in enumerate(build(n=100, seed=7, templates=HELDOUT_TEMPLATES)):
        output = deidentifier.deidentify(snippet.text, encounter_id=f"held-{i}").text.text
        for entity, value in snippet.phi:
            held_totals[entity] += 1
            if leaked(entity, value, output):
                held_misses[(entity, i % len(HELDOUT_TEMPLATES))] += 1
            else:
                held_caught[entity] += 1
    held_rows = [
        {"entity": e, "n": held_totals[e], "recall": round(held_caught[e] / held_totals[e], 3)}
        for e in (*NER, *STRUCTURED)
        if held_totals[e]
    ]

    rows, failed = [], []
    for entity in (*STRUCTURED, *NER):
        if not totals[entity]:
            continue
        recall = caught[entity] / totals[entity]
        gate = RECALL_GATES[entity]
        rows.append(
            {"entity": entity, "n": totals[entity], "recall": round(recall, 3), "gate": gate}
        )
        if recall < gate:
            failed.append(f"{entity} recall {recall:.3f} < {gate}")
    if over_rate > MAX_OVER_REDACTION:
        failed.append(f"over-redaction {over_rate:.1%} > {MAX_OVER_REDACTION:.0%}")

    summary = {
        "snippets": len(corpus),
        "seed": 42,
        "latency_ms_p50": round(p50, 1),
        "latency_ms_p95": round(p95, 1),
        "results": rows,
        "misses_by_template": {f"{e}@t{t}": n for (e, t), n in sorted(misses.items())},
        "negative_sentences": len(SENTENCES),
        "over_redacted": len(over),
        "over_redaction_rate": round(over_rate, 4),
        "heldout": held_rows,
        "heldout_misses_by_template": {f"{e}@h{t}": n for (e, t), n in sorted(held_misses.items())},
        "gate_passed": not failed,
        "failed": failed,
    }
    return summary, over, elapsed


if __name__ == "__main__":
    sys.exit(main())
