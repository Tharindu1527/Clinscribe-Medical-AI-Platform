"""Lab-mode evaluation (Phase 5; SPEC section 11: OCR accuracy table).

For each of N Synthea patients: their most recent lab panel (tests in config/lab_reference.yaml)
is rendered as a report PDF, parsed back, and every parsed field is compared with the source
Observation: test mapped to the right LOINC code, value, unit, and the H/L/N flag against the
reference interval. The wrong-patient control checks each report against another patient's record.
Reports here are text PDFs with one fixed layout; scanned images (true OCR) are not covered.

  uv run python -m evals.lab.lab_eval [--n 20]      (needs `just up` + `just fhir-load`)
"""

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

from agents.lab.parser import identity_matches, parse, reference
from agents.lab.pdf import report_lines, write_pdf
from config.settings import Settings

REPORT = Path(__file__).resolve().parents[2] / "evals" / "reports" / "lab" / "lab_parser.md"


def fetch(client: httpx.Client, path: str, **params: str) -> list[dict[str, Any]]:
    response = client.get(path, params={**params, "_count": "500"})
    response.raise_for_status()
    return [e["resource"] for e in response.json().get("entry", [])]


def latest_panel(observations: list[dict[str, Any]], known: set[str]) -> list[dict[str, Any]]:
    numeric = [
        o
        for o in observations
        if o.get("valueQuantity")
        and o["code"]["coding"][0]["code"] in known
        and o.get("effectiveDateTime")
    ]
    if not numeric:
        return []
    day = max(o["effectiveDateTime"][:10] for o in numeric)
    panel = {
        o["code"]["coding"][0]["code"]: o for o in numeric if o["effectiveDateTime"][:10] == day
    }
    return list(panel.values())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=20)
    args = parser.parse_args(argv)
    ref = reference()
    client = httpx.Client(
        base_url=Settings().fhir_base_url.rstrip("/") + "/",
        timeout=60,
        headers={"Cache-Control": "no-cache"},
    )
    patients = fetch(client, "Patient")
    counts: Counter[str] = Counter()
    rows = []
    cases = []
    for patient in patients:
        panel = latest_panel(
            fetch(client, "Observation", patient=patient["id"], category="laboratory"), set(ref)
        )
        if panel:
            cases.append((patient, panel))
        if len(cases) == args.n:
            break
    for n, (patient, panel) in enumerate(cases):
        name = " ".join([*patient["name"][0].get("given", []), patient["name"][0]["family"]])
        printed = []
        for obs in panel:
            code = obs["code"]["coding"][0]["code"]
            info = ref[code]
            value = obs["valueQuantity"]["value"]
            printed.append(
                (
                    info["name"],
                    f"{value:g}",
                    obs["valueQuantity"]["unit"],
                    f"{info['low']:g} - {info['high']:g}",
                )
            )
        collected = panel[0]["effectiveDateTime"][:10]
        report = parse(write_pdf(report_lines(name, patient["birthDate"], collected, printed)))
        by_name = {r.name: r for r in report.results}
        for obs, (printed_name, *_rest) in zip(panel, printed, strict=True):
            code = obs["code"]["coding"][0]["code"]
            value, unit = float(obs["valueQuantity"]["value"]), obs["valueQuantity"]["unit"]
            info = ref[code]
            expected_flag = "H" if value > info["high"] else "L" if value < info["low"] else "N"
            got = by_name.get(printed_name)
            counts["values"] += 1
            counts["found"] += got is not None
            counts["code"] += got is not None and got.loinc == code
            counts["value"] += got is not None and abs(got.value - value) < 1e-9
            counts["unit"] += got is not None and got.unit == unit and got.unit_matches
            counts["flag"] += got is not None and got.flag == expected_flag
            counts["abnormal"] += expected_flag != "N"
        counts["unreadable"] += len(report.unreadable_rows)
        identity = identity_matches(report, patient)
        counts["reports"] += 1
        counts["identity_ok"] += all(identity.values())
        other = cases[(n + 1) % len(cases)][0]  # wrong-patient control
        counts["wrong_patient_caught"] += not all(identity_matches(report, other).values())
        flagged = sum(r.flag in ("H", "L") for r in report.results)
        rows.append((patient["id"], len(panel), collected, flagged))
    total = counts["values"]
    lines = [
        "# Lab mode: report PDF -> FHIR Observations (Phase 5)",
        "",
        f"{counts['reports']} Synthea patients' latest lab panels rendered as text PDFs (one fixed",
        "layout) and parsed back with `agents/lab/parser.py` (pypdf text, no model). Reference",
        "intervals: `config/lab_reference.yaml` (illustrative adult values).",
        "",
        "| field | correct | of |",
        "|---|---|---|",
        f"| test row found | {counts['found']} | {total} |",
        f"| mapped to the right LOINC code | {counts['code']} | {total} |",
        f"| value exact | {counts['value']} | {total} |",
        f"| unit as expected | {counts['unit']} | {total} |",
        f"| H/L/N flag | {counts['flag']} | {total} ({counts['abnormal']} abnormal) |",
        f"| report identity matches its patient | {counts['identity_ok']} | {counts['reports']} |",
        f"| wrong-patient control caught | {counts['wrong_patient_caught']} "
        f"| {counts['reports']} |",
        f"| unreadable rows | {counts['unreadable']} | — |",
        "",
        "Limits: one synthetic layout; no scanned images, handwriting, multi-column or",
        "vendor-specific layouts. A real deployment needs OCR (Docling or Tesseract) and a layout",
        "test set per lab.",
        "",
        "| patient | tests | collected | flagged H/L |",
        "|---|---|---|---|",
        *[f"| {pid} | {k} | {day} | {flagged} |" for pid, k, day, flagged in rows],
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines[:17]))
    ok = counts["code"] == counts["value"] == counts["flag"] == total and (
        counts["wrong_patient_caught"] == counts["reports"]
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
