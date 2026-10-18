"""Scribe from consultation audio (SPEC sections 4 and 11): diarization, roles, WER, drafts.

PriMock57 (CC BY 4.0, role-played, no real patients) records the doctor and the patient on separate
channels with time-aligned transcripts, so the two channels mixed give one-microphone consultation
audio with a known speaker at every moment. The mix streams through the Scribe listener's own code
(voice/scribe.py: Deepgram nova-3-medical live, diarization on) at SPEED x real time, and:
- speaker attribution: share of recognised words whose role (voice/scribe.assign_roles) matches the
  channel speaking at the word's midpoint; words in overlapping speech or outside every reference
  interval are not scored (coverage is reported);
- diarization purity: the same, with each diarized speaker given its majority role (an oracle that
  separates diarization errors from role-assignment errors);
- role rule: whether the first-speaker rule named the right speaker as the doctor;
- WER of the mix (both references merged in time order) vs nova-3-medical on the separate channels
  (evals/reports/voice/asr_wer.md);
- drafts: the first N diarized consultations go to POST /v1/scribe/drafts (the real note writer).
Recognised words are cached in data/raw/primock57/scribe_cache (reruns cost nothing).

  uv run --group voice python -m evals.voice.scribe_eval [--drafts 2]   (needs DEEPGRAM_API_KEY;
  drafts need `just up rag`)
"""

import argparse
import asyncio
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import websockets

from apps.api.auth import issue_token
from config.settings import Settings
from evals.voice.asr_eval import CONSULTATIONS, DATA, align, normalise
from voice.scribe import (
    RATE,
    Word,
    assign_roles,
    group_turns,
    pcm_source,
    post_draft,
    read_wav,
    transcribe,
    transcript_for_api,
)

ROOT = Path(__file__).resolve().parents[2]
CACHE = DATA / "scribe_cache"
REPORT = ROOT / "evals" / "reports" / "voice" / "scribe_diarization.md"
SPEED = 2.0  # Deepgram reads a faster stream at about 2x anyway (measured)
PATIENT = "1617"  # synthetic Synthea patient the eval drafts are filed under (never approved)
SEPARATE_CHANNEL_WER = 0.112  # nova-3-medical, evals/reports/voice/asr_wer.md
Interval = tuple[float, float, str]
INTERVAL = re.compile(r'xmin = ([\d.]+)\s*\n\s*xmax = ([\d.]+)\s*\n\s*text = "(.*)"')


def intervals(grid: str) -> list[Interval]:
    """Non-empty (start, end, text) intervals of a PriMock57 TextGrid."""
    return [(float(a), float(b), t) for a, b, t in INTERVAL.findall(grid) if t.strip()]


def reference_role(t: float, doctor: list[Interval], patient: list[Interval]) -> str | None:
    in_doctor = any(a <= t <= b for a, b, _ in doctor)
    in_patient = any(a <= t <= b for a, b, _ in patient)
    if in_doctor != in_patient:
        return "doctor" if in_doctor else "patient"
    return None  # overlapping speech, or no reference speech


def mix(consultation: str) -> bytes:
    channels = [
        np.frombuffer(read_wav(DATA / "audio" / f"{consultation}_{s}.wav"), dtype="<i2")
        for s in ("doctor", "patient")
    ]
    length = max(len(c) for c in channels)
    total = np.zeros(length, dtype=np.int32)
    for channel in channels:
        total[: len(channel)] += channel
    return np.clip(total, -32768, 32767).astype("<i2").tobytes()


def diarize(consultation: str) -> list[Word]:
    path = CACHE / f"{consultation}.json"
    if path.exists():
        return [Word(**w) for w in json.loads(path.read_text(encoding="utf-8"))]
    try:
        words = asyncio.run(transcribe(pcm_source(mix(consultation), SPEED)))
    except (websockets.ConnectionClosedError, OSError) as exc:  # one retry on a dropped stream
        print(f"{consultation}: stream dropped ({type(exc).__name__}), retrying once", flush=True)
        words = asyncio.run(transcribe(pcm_source(mix(consultation), SPEED)))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(w) for w in words]), encoding="utf-8")
    return words


def score(words: list[Word], doctor: list[Interval], patient: list[Interval]) -> dict[str, Any]:
    turns = group_turns(words)
    roles = assign_roles(turns)  # rule v2: main speakers only, fragments "unknown"
    roles_v1 = assign_roles(turns, min_share=0.0)  # rule v1: every speaker counts
    known = [(w, r) for w in words if (r := reference_role((w.start + w.end) / 2, doctor, patient))]
    by_speaker: dict[int, Counter[str]] = defaultdict(Counter)
    for word, role in known:
        by_speaker[word.speaker][role] += 1
    doctor_speaker = max(by_speaker, key=lambda s: by_speaker[s]["doctor"]) if by_speaker else -1
    merged = sorted(
        [(a, "doctor", t) for a, _, t in doctor] + [(a, "patient", t) for a, _, t in patient]
    )
    reference_turns = sum(1 for i, x in enumerate(merged) if i == 0 or x[1] != merged[i - 1][1])
    ref = normalise(" ".join(t for _, _, t in merged))
    hyp = normalise(" ".join(w.text for w in sorted(words, key=lambda w: w.start)))
    distance, _ = align(ref, hyp)
    return {
        "words": len(words),
        "scored": len(known),
        "attribution": sum(roles[w.speaker] == r for w, r in known) / max(1, len(known)),
        "attribution_v1": sum(roles_v1[w.speaker] == r for w, r in known) / max(1, len(known)),
        "purity": sum(c.most_common(1)[0][1] for c in by_speaker.values()) / max(1, len(known)),
        "speakers": len(by_speaker),
        "rule_ok": roles.get(doctor_speaker) == "doctor",
        "rule_v1_ok": roles_v1.get(doctor_speaker) == "doctor",
        "wer": distance / max(1, len(ref)),
        "ref_words": len(ref),
        "turns": len(turns),
        "reference_turns": reference_turns,
    }


def draft(words: list[Word], token: str) -> dict[str, Any]:
    turns = group_turns(words)
    transcript = transcript_for_api(turns, assign_roles(turns))
    try:
        out = post_draft(transcript, PATIENT, token)
    except httpx.HTTPStatusError as exc:
        detail = exc.response.json().get("detail", "") if exc.response.content else ""
        return {
            "ok": False,
            "turns": len(transcript),
            "error": f"{exc.response.status_code} {detail}",
        }
    return {
        "ok": True,
        "turns": len(transcript),
        "draft_id": out["draft_id"],
        "statements": len(out["draft"]["statements"]),
        "unsupported": len(out["unsupported"]),
        "removed": len(out["removed"]),
    }


def report(rows: list[dict[str, Any]], drafts: list[dict[str, Any]]) -> str:
    known = sum(r["scored"] for r in rows)
    pooled = {
        key: sum(r[key] * r["scored"] for r in rows) / max(1, known)
        for key in ("attribution", "attribution_v1", "purity")
    }
    wer = sum(r["wer"] * r["ref_words"] for r in rows) / max(1, sum(r["ref_words"] for r in rows))
    lines = [
        "# Scribe from consultation audio: diarization, roles, WER",
        "",
        f"PriMock57, {len(rows)} consultations, doctor and patient channels mixed to one stream, "
        f"Deepgram nova-3-medical live with diarization (voice/scribe.py), streamed at {SPEED:g}x "
        "real time. Generated by `evals/voice/scribe_eval.py`. Role rule v1: the first speaker "
        "of a "
        "3+ word turn is the doctor; v2 (the listener's): the same among main speakers (5%+ of the "
        "words), smaller fragments 'unknown'. **v2 was designed after v1 failed on "
        "day1_consultation01** (a 3-word fragment opened it), so its score is optimistic.",
        "",
        "| Consultation | Words | Scored | Speakers | Doctor found v1 / v2 | Attribution v1 / v2 "
        "| Purity | WER | Turns (ref) | Heard until |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['name']} | {r['words']} | {r['scored']} | {r['speakers']} | "
            f"{'ok' if r['rule_v1_ok'] else 'wrong'} / {'ok' if r['rule_ok'] else 'wrong'} | "
            f"{r['attribution_v1']:.3f} / {r['attribution']:.3f} | {r['purity']:.3f} | "
            f"{r['wer']:.3f} | {r['turns']} ({r['reference_turns']}) | "
            f"{r['last_word_s']:.0f} of {r['audio_s']:.0f} s |"
        )
    rule = sum(r["rule_ok"] for r in rows)
    rule_v1 = sum(r["rule_v1_ok"] for r in rows)
    lines += [
        "",
        f"- **Speaker attribution (pooled over {known:,} scored words): v2 "
        f"{pooled['attribution']:.3f}**, v1 {pooled['attribution_v1']:.3f}; diarization purity "
        "(each speaker given its majority role, the ceiling for any rule): "
        f"{pooled['purity']:.3f}.",
        f"- Doctor identified in **{rule} of {len(rows)}** consultations with v2, "
        f"{rule_v1} with v1.",
        f"- WER on the mixed stream **{wer:.3f}** vs {SEPARATE_CHANNEL_WER:.3f} on separate "
        "channels (same model; the reference order of overlapping speech is approximate, which "
        "counts against "
        "the mix).",
        "- Words were recorded before `numerals=true` was added to the listener (it writes numbers "
        "as digits for the dose guardrail); that changes number formatting, and was not "
        "re-measured "
        "here.",
        "- Heard until: the last recognised word against the recording's length (a cut-off "
        "transcript shows here; a first run lost the last 25-30% this way, now fixed).",
        "- Scored words: midpoint inside exactly one speaker's reference interval; the rest is "
        "overlap or silence in the reference.",
    ]
    if drafts:
        ok = [d for d in drafts if d["ok"]]
        lines += ["", "## Drafts from the diarized transcripts", ""]
        lines += ["| Consultation | Turns sent | Result |", "|---|---|---|"]
        for d in drafts:
            result = (
                f"{d['statements']} statements, {d['unsupported']} without a guideline source, "
                f"{d['removed']} removed by guardrails"
                if d["ok"]
                else f"failed: {d['error']}"
            )
            lines.append(f"| {d['name']} | {d['turns']} | {result} |")
        lines += [
            "",
            f"{len(ok)} of {len(drafts)} drafts produced (filed under synthetic patient "
            f"{PATIENT}, left unapproved).",
        ]
    lines += [
        "",
        "Notes: mixing two close-talk channels is cleaner than one room microphone (no "
        "reverberation, "
        "no distance); a real room is harder. Six consultations, one recording setup: small n.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--drafts", type=int, default=0, help="consultations to send as drafts")
    args = parser.parse_args(argv)
    rows: list[dict[str, Any]] = []
    drafts: list[dict[str, Any]] = []
    token = issue_token("dr-demo", Settings().auth_token_key)
    for index, consultation in enumerate(CONSULTATIONS):
        grids = {
            s: intervals((DATA / "transcripts" / f"{consultation}_{s}.TextGrid").read_text("utf-8"))
            for s in ("doctor", "patient")
        }
        words = diarize(consultation)
        audio_s = len(mix(consultation)) / 2 / RATE
        last_word_s = max((w.end for w in words), default=0.0)
        scored = score(words, grids["doctor"], grids["patient"])
        rows.append(
            {"name": consultation, **scored, "last_word_s": last_word_s, "audio_s": audio_s}
        )
        print(f"{consultation}: {rows[-1]}", flush=True)
        if index < args.drafts:
            drafts.append({"name": consultation, **draft(words, token)})
            print(f"  draft: {drafts[-1]}", flush=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(report(rows, drafts), encoding="utf-8")
    print(f"wrote {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
