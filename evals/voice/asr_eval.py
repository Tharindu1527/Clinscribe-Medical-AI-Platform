"""Medical speech recognition benchmark (Phase 4; SPEC section 4 and 11).

PriMock57 (CC BY 4.0, mock primary-care consultations, separate doctor and patient channels with
time-aligned transcripts): 6 consultations, both channels. Deepgram prerecorded API over HTTP (no
SDK), three configurations:
- nova-3                     the general model
- nova-3 + keyterms          keyterm prompting with the corpus drug list and general clinical words
                             (built without looking at these transcripts)
- nova-3-medical             Deepgram's medical model
Metrics: WER on normalised text (lowercase, punctuation and transcript tags removed, filler words
dropped from both sides), and the medical-term error rate: the share of reference medical terms
(single-word RxNorm lexicon entries + a fixed clinical word list) not matched in the alignment.
Raw audio goes to the vendor (SPEC section 8: a BAA-covered vendor would be required for real PHI);
PriMock57 is role-played, no real patients. Responses cached in data/raw/primock57/asr_cache.

  uv run python -m evals.voice.asr_eval      (needs DEEPGRAM_API_KEY; ~$1.5 of free credit, once)
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
import yaml

from config.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "raw" / "primock57"
CACHE = DATA / "asr_cache"
REPORT = ROOT / "evals" / "reports" / "voice" / "asr_wer.md"
CONSULTATIONS = [
    "day1_consultation01",
    "day1_consultation05",
    "day2_consultation03",
    "day3_consultation02",
    "day4_consultation04",
    "day5_consultation06",
]
FILLERS = {"um", "uh", "erm", "er", "hmm", "mm", "mhm", "ah", "eh", "uhm", "mmm", "hm"}
CLINICAL_WORDS = [
    "abdominal",
    "allergy",
    "allergies",
    "antibiotic",
    "antibiotics",
    "anxiety",
    "asthma",
    "blood",
    "bloating",
    "breathless",
    "cholesterol",
    "chest",
    "constipation",
    "cough",
    "cramps",
    "depression",
    "diabetes",
    "diarrhoea",
    "diarrhea",
    "dizziness",
    "dizzy",
    "eczema",
    "fever",
    "headache",
    "headaches",
    "heartburn",
    "hypertension",
    "infection",
    "inflammation",
    "inhaler",
    "insulin",
    "migraine",
    "nausea",
    "palpitations",
    "paracetamol",
    "ibuprofen",
    "pneumonia",
    "prescription",
    "rash",
    "sputum",
    "stomach",
    "swelling",
    "symptoms",
    "tablets",
    "temperature",
    "thyroid",
    "urinary",
    "urine",
    "vomiting",
    "wheezing",
]
VARIANTS: dict[str, dict[str, Any]] = {
    "nova-3": {"model": "nova-3"},
    "nova-3 + keyterms": {"model": "nova-3", "keyterms": True},
    "nova-3-medical": {"model": "nova-3-medical"},
}


def normalise(text: str) -> list[str]:
    text = re.sub(r"</?UNSURE>", " ", text)
    text = re.sub(r"<[^>]+/>|<[^>]+>", " ", text)
    text = text.lower().replace("’", "'")
    words = re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text)
    return [w for w in words if w not in FILLERS]


def reference(name: str) -> str:
    grid = (DATA / "transcripts" / f"{name}.TextGrid").read_text(encoding="utf-8")
    return " ".join(re.findall(r'text = "(.*)"', grid))


def keyterms() -> list[str]:
    corpus = yaml.safe_load((ROOT / "config" / "corpus.yaml").read_text(encoding="utf-8"))
    drugs = [str(d).split(" (")[0] for d in corpus["openfda"]["drugs"]]
    terms = list(dict.fromkeys([*drugs, *CLINICAL_WORDS]))
    return terms[:100]  # Deepgram keyterm limit per request


def medical_terms() -> set[str]:
    lexicon = (ROOT / "privacy" / "deid" / "resources" / "clinical_lexicon.txt").read_text(
        encoding="utf-8"
    )
    singles = {
        line.strip().lower()
        for line in lexicon.splitlines()
        if line and not line.startswith("#") and re.fullmatch(r"[A-Za-z]{5,}", line.strip())
    }
    return singles | set(CLINICAL_WORDS)


def align(ref: list[str], hyp: list[str]) -> tuple[int, list[bool]]:
    """Edit distance and, per reference word, whether the alignment matched it."""
    n, m = len(ref), len(hyp)
    dist = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dist[i][0] = i
    for j in range(m + 1):
        dist[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            dist[i][j] = min(
                dist[i - 1][j] + 1,
                dist[i][j - 1] + 1,
                dist[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]),
            )
    matched = [False] * n
    i, j = n, m
    while i > 0 and j > 0:
        if ref[i - 1] == hyp[j - 1] and dist[i][j] == dist[i - 1][j - 1]:
            matched[i - 1] = True
            i, j = i - 1, j - 1
        elif dist[i][j] == dist[i - 1][j - 1] + 1:
            i, j = i - 1, j - 1
        elif dist[i][j] == dist[i - 1][j] + 1:
            i -= 1
        else:
            j -= 1
    return dist[n][m], matched


def transcribe(name: str, variant: str, terms: list[str]) -> str:
    path = CACHE / variant.replace(" ", "_").replace("+", "plus") / f"{name}.json"
    if path.exists():
        return str(json.loads(path.read_text(encoding="utf-8"))["transcript"])
    cfg = VARIANTS[variant]
    params: list[tuple[str, str | int | float | bool | None]] = [
        ("model", str(cfg["model"])),
        ("smart_format", "false"),
    ]
    if cfg.get("keyterms"):
        params += [("keyterm", t) for t in terms]
    response = httpx.post(
        "https://api.deepgram.com/v1/listen",
        params=params,
        headers={
            "Authorization": f"Token {Settings().deepgram_api_key.get_secret_value()}",
            "Content-Type": "audio/wav",
        },
        content=(DATA / "audio" / f"{name}.wav").read_bytes(),
        timeout=600,
    )
    response.raise_for_status()
    alt = response.json()["results"]["channels"][0]["alternatives"][0]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"transcript": alt["transcript"]}), encoding="utf-8")
    return str(alt["transcript"])


def main() -> int:
    terms, medical = keyterms(), medical_terms()
    totals: dict[str, Counter[str]] = {v: Counter() for v in VARIANTS}
    per_file: list[dict[str, Any]] = []
    for consultation in CONSULTATIONS:
        for speaker in ("doctor", "patient"):
            name = f"{consultation}_{speaker}"
            ref = normalise(reference(name))
            row: dict[str, Any] = {"file": name, "words": len(ref)}
            for variant in VARIANTS:
                hyp = normalise(transcribe(name, variant, terms))
                errors, matched = align(ref, hyp)
                med = [ok for word, ok in zip(ref, matched, strict=True) if word in medical]
                totals[variant].update(
                    {
                        f"err_{speaker}": errors,
                        f"words_{speaker}": len(ref),
                        "med": len(med),
                        "med_missed": med.count(False),
                    }
                )
                row[variant] = errors / max(len(ref), 1)
            per_file.append(row)
            print(name, {k: round(v, 3) if isinstance(v, float) else v for k, v in row.items()})
    lines = [
        "# Medical speech recognition: Deepgram on PriMock57 (Phase 4)",
        "",
        f"6 PriMock57 consultations (CC BY 4.0), doctor and patient channels separately "
        f"({sum(r['words'] for r in per_file):,} reference words after normalisation). Keyterms: "
        f"{len(terms)} (corpus drug list + general clinical words, not taken from these "
        "transcripts).",
        "",
        "| configuration | WER all | WER doctor | WER patient | medical-term error rate |",
        "|---|---|---|---|---|",
    ]
    for variant, t in totals.items():
        all_err = t["err_doctor"] + t["err_patient"]
        all_words = t["words_doctor"] + t["words_patient"]
        lines.append(
            f"| {variant} | {all_err / all_words:.3f} | "
            f"{t['err_doctor'] / t['words_doctor']:.3f} | "
            f"{t['err_patient'] / t['words_patient']:.3f} | "
            f"{t['med_missed'] / max(t['med'], 1):.3f} ({t['med_missed']}/{t['med']}) |"
        )
    lines += [
        "",
        "Normalisation: lowercase, punctuation and transcript tags removed, filler words (um, uh,",
        "erm ...) dropped from reference and hypothesis. Medical terms: single-word RxNorm lexicon",
        "entries (5+ letters) and a fixed list of clinical words. No AssemblyAI comparison",
        "(no key).",
        "",
        "| file | words | " + " | ".join(VARIANTS) + " |",
        "|---|---|" + "---|" * len(VARIANTS),
        *[
            f"| {r['file']} | {r['words']} | " + " | ".join(f"{r[v]:.3f}" for v in VARIANTS) + " |"
            for r in per_file
        ],
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines[:10]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
