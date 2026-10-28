"""Record the review UI's demo data (apps/web/src/demo/fixtures.json) from the running API.

Demo mode (`just ui-demo`) answers from these responses, so the UI can be tried without the stack.
Everything recorded is synthetic: guideline questions, a synthetic consultation draft, a Synthea
patient's lab panel sent as an HL7 v2 message, and the audit rows of demo users. No token is
written or printed. Needs `just up rag` and, for the draft, one waiting draft (the newest is used).

  just ui-fixtures            (about 30 s: three Ask calls, one of them agentic)
"""

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from agents.lab.hl7 import build_oru
from agents.lab.parser import reference
from apps.api.auth import issue_token
from config.settings import Settings
from evals.lab.hl7_eval import mrn
from evals.lab.lab_eval import fetch, latest_panel

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "apps" / "web" / "src" / "demo" / "fixtures.json"
API = "http://127.0.0.1:8000"
QUESTIONS = [  # fast path, agentic path with a drug-interaction fact, and an abstention
    "What is the maximum daily dose of metformin?",
    "Does clarithromycin interact with warfarin?",
    "Which gastrointestinal side effects does mazdutide cause?",
]


def lab_case(fhir: httpx.Client, ref: dict[str, Any]) -> tuple[dict[str, Any], list[Any]]:
    """The first Synthea patient with a full panel and at least two abnormal values."""
    for patient in fetch(fhir, "Patient"):
        panel = latest_panel(
            fetch(fhir, "Observation", patient=patient["id"], category="laboratory"), set(ref)
        )
        out = 0
        for obs in panel:
            info = ref[obs["code"]["coding"][0]["code"]]
            value = float(obs["valueQuantity"]["value"])
            out += value > info["high"] or value < info["low"]
        if len(panel) >= 8 and out >= 2:
            return patient, panel
    raise SystemExit("no Synthea patient with a full lab panel (just fhir-load)")


def main() -> int:
    key = Settings().auth_token_key
    doctor = {"Authorization": f"Bearer {issue_token('dr-demo', key)}"}
    admin = {"Authorization": f"Bearer {issue_token('admin-demo', key)}"}
    api = httpx.Client(base_url=API, timeout=300)
    data: dict[str, Any] = {"ask": []}
    for question in QUESTIONS:
        started = time.perf_counter()
        body = {"encounter_id": f"demo-{uuid.uuid4().hex[:8]}", "question": question}
        r = api.post("/v1/ask?identified=true", json=body, headers=doctor)
        r.raise_for_status()
        data["ask"].append({"question": question, "response": r.json()})
        print(f"ask: {question} ({time.perf_counter() - started:.1f} s)", file=sys.stderr)

    waiting = api.get("/v1/drafts", headers=doctor).raise_for_status().json()
    if not waiting:
        raise SystemExit(
            "no draft is waiting for review: create one first (just scribe, or the UI)"
        )
    data["drafts"] = waiting[:3]
    newest = waiting[0]["draft_id"]
    data["draft"] = (
        api.get(f"/v1/drafts/{newest}?identified=true", headers=doctor).raise_for_status().json()
    )

    ref = reference()
    fhir = httpx.Client(
        base_url=Settings().fhir_base_url.rstrip("/") + "/",
        timeout=60,
        headers={"Cache-Control": "no-cache"},
    )
    patient, panel = lab_case(fhir, ref)
    name = patient["name"][0]
    results = []
    for obs in panel:
        code = obs["code"]["coding"][0]["code"]
        info, value = ref[code], float(obs["valueQuantity"]["value"])
        flag = "H" if value > info["high"] else "L" if value < info["low"] else "N"
        unit = obs["valueQuantity"]["unit"]
        results.append((code, info["name"], value, unit, f"{info['low']:g}-{info['high']:g}", flag))
    message = build_oru(
        mrn=mrn(patient),
        family=name["family"],
        given=name.get("given", []),
        birth_date=patient["birthDate"],
        collected=panel[0]["effectiveDateTime"][:10],
        results=results,
        message_id="DEMO0001",
    )
    parsed = api.post(
        "/v1/lab/parse", json={"patient_id": patient["id"], "hl7_message": message}, headers=doctor
    ).raise_for_status()
    data["lab"] = {"patient_id": patient["id"], "hl7_message": message, "response": parsed.json()}
    data["audit"] = api.get("/v1/audit?limit=40", headers=admin).raise_for_status().json()
    OUT.write_text(
        json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size:,} bytes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
