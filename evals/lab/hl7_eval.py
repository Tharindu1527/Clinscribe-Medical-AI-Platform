"""HL7 v2 ORU^R01 -> Lab mode (ADR-0021; SPEC section 8 interoperability).

For each of N Synthea patients: their most recent lab panel (tests in config/lab_reference.yaml)
is written as an ORU^R01 message with the record's MRN, name and birth date, read back with
`agents/lab/hl7.py`, and every result is compared with the source Observation: LOINC code, value,
unit, and the H/L/N flag against the reference interval. Each message is also read with newline
segment endings and inside MLLP framing (the result must not change), and checked against another
patient's record (wrong-patient control: name, birth date and MRN). Messages come from one
synthetic sender; real senders vary (local codes, Z-segments, other versions).

  uv run python -m evals.lab.hl7_eval [--n 20]      (needs `just up` + `just fhir-load`)
"""

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

from agents.lab.hl7 import build_oru, parse_oru
from agents.lab.parser import identity_matches, reference, to_observation
from config.settings import Settings
from evals.lab.lab_eval import fetch, latest_panel

REPORT = Path(__file__).resolve().parents[2] / "evals" / "reports" / "lab" / "hl7_oru.md"


def mrn(patient: dict[str, Any]) -> str:
    return str(
        next(
            i["value"]
            for i in patient.get("identifier", [])
            if any(c.get("code") == "MR" for c in i.get("type", {}).get("coding", []))
        )
    )


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
    cases = []
    for patient in fetch(client, "Patient"):
        panel = latest_panel(
            fetch(client, "Observation", patient=patient["id"], category="laboratory"), set(ref)
        )
        if panel:
            cases.append((patient, panel))
        if len(cases) == args.n:
            break
    counts: Counter[str] = Counter()
    rows = []
    for n, (patient, panel) in enumerate(cases):
        name = patient["name"][0]
        collected = panel[0]["effectiveDateTime"][:10]
        expected = []
        for obs in panel:
            code = obs["code"]["coding"][0]["code"]
            info, value = ref[code], float(obs["valueQuantity"]["value"])
            flag = "H" if value > info["high"] else "L" if value < info["low"] else "N"
            expected.append((code, info["name"], value, obs["valueQuantity"]["unit"], info, flag))
        message = build_oru(
            mrn=mrn(patient),
            family=name["family"],
            given=name.get("given", []),
            birth_date=patient["birthDate"],
            collected=collected,
            results=[
                (code, label, value, unit, f"{info['low']:g}-{info['high']:g}", flag)
                for code, label, value, unit, info, flag in expected
            ],
            message_id=f"EVAL{n:04d}",
        )
        report = parse_oru(message)
        variants = (message.replace("\r", "\n"), f"\x0b{message}\x1c\r")
        counts["framing_same"] += all(parse_oru(v) == report for v in variants)
        by_code = {r.loinc: r for r in report.results}
        mapped = 0
        for code, _label, value, unit, _info, flag in expected:
            got = by_code.get(code)
            counts["values"] += 1
            counts["code"] += got is not None
            counts["value"] += got is not None and abs(got.value - value) < 1e-9
            counts["unit"] += got is not None and got.unit == unit and got.unit_matches
            counts["flag"] += got is not None and got.flag == flag
            counts["abnormal"] += flag != "N"
            if got is not None:
                to_observation(got, patient["id"], report.collected)  # raises if not mappable
                mapped += 1
        counts["observations"] += mapped
        counts["unreadable"] += len(report.unreadable_rows)
        counts["messages"] += 1
        counts["collected"] += report.collected == collected
        counts["identity_ok"] += identity_matches(report, patient) == {
            "name": True,
            "birth_date": True,
            "mrn": True,
        }
        other = cases[(n + 1) % len(cases)][0]  # wrong-patient control
        wrong = identity_matches(report, other)
        counts["wrong_patient_caught"] += not all(wrong.values())
        counts["wrong_mrn_caught"] += not wrong["mrn"]
        rows.append((patient["id"], len(panel), collected, sum(f != "N" for *_, f in expected)))
    total = counts["values"]
    messages = counts["messages"]
    lines = [
        "# Lab mode: HL7 v2 ORU^R01 -> FHIR Observations (ADR-0021)",
        "",
        f"{messages} Synthea patients' latest lab panels written as ORU^R01 (v2.5.1) messages with",
        "the record's MRN, name and birth date, then read back with `agents/lab/hl7.py` (no",
        "model).",
        "Reference intervals: `config/lab_reference.yaml` (illustrative adult values).",
        "",
        "| check | correct | of |",
        "|---|---|---|",
        f"| result mapped to the right LOINC code | {counts['code']} | {total} |",
        f"| value exact | {counts['value']} | {total} |",
        f"| unit as expected (UCUM) | {counts['unit']} | {total} |",
        f"| H/L/N flag | {counts['flag']} | {total} ({counts['abnormal']} abnormal) |",
        f"| preliminary FHIR Observation built | {counts['observations']} | {total} |",
        f"| collection date | {counts['collected']} | {messages} |",
        f"| identity matches its record (name, birth date, MRN) | {counts['identity_ok']} "
        f"| {messages} |",
        f"| wrong-patient control caught | {counts['wrong_patient_caught']} | {messages} |",
        f"| ... of which by the MRN alone | {counts['wrong_mrn_caught']} | {messages} |",
        f"| same result with newline endings and MLLP framing | {counts['framing_same']} "
        f"| {messages} |",
        f"| results listed as not readable | {counts['unreadable']} | — |",
        "",
        "Limits: one synthetic sender, written by the same project as the reader, so this shows",
        "the mapping and the checks, not robustness to real senders (local codes instead of LOINC,",
        "structured numerics such as `>60`, Z-segments, v2.3 vs 2.5.1 differences, batches).",
        "Unit tests cover escape sequences, other separators, non-numeric and non-final results.",
        "",
        "| patient | tests | collected | flagged H/L |",
        "|---|---|---|---|",
        *[f"| {pid} | {k} | {day} | {flagged} |" for pid, k, day, flagged in rows],
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines[:20]))
    ok = (
        counts["code"] == counts["value"] == counts["unit"] == counts["flag"] == total
        and counts["identity_ok"] == counts["wrong_patient_caught"] == messages
        and counts["framing_same"] == messages
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
