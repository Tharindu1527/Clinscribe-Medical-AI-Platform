"""Low-confidence speech for the doctor's review (SPEC sections 4, 5 and 8; ADR-0027).

Deepgram gives every recognised word a confidence. The Scribe listener sends the words under a
threshold with each turn, and the review screen shows them on the statements that rely on them (a
misheard drug name is a SPEC section 8 hazard). This measures on PriMock57 (CC BY 4.0, role-played,
no real patients) how many recognition errors a threshold catches and how many words it flags, and
chooses the threshold by a rule written down before the first run:

  the largest grid value whose flag rate is at most 5% of the scored words (the doctor's checking
  burden), chosen on one half of the consultations and measured on the other (2-fold over
  consultations); the listener uses the value chosen on all six.

Words: the doctor and patient channels mixed and streamed through the listener's own code
(voice/scribe.py: nova-3-medical live, diarization and numerals on) at 2x real time, as in
evals/voice/scribe_eval.py; cached in data/raw/primock57/confidence_cache (reruns cost nothing).
Errors: the recognised words aligned to the reference (both channels' transcripts in time order,
normalised as in evals/voice/asr_eval.py); a word is wrong when one of its tokens is substituted or
inserted. Not scored: words with digits (numerals=true writes "500" where the reference says
"five hundred") and filler words. Overlapping speech makes the reference order approximate, which
counts some right words as wrong. Medical errors: a substitution or insertion where either side is a
medical term (asr_eval.medical_terms); a medical term the recogniser left out entirely leaves no
word to highlight and is counted apart.

With --drafts N, the first N consultations also go to the API as drafts (the real note writer;
`just up rag` with this code), and the report counts the statements the review screen flags; the
drafts are then rejected, so nothing waits for review. Each draft's de-identified transcript,
statements and unsure words are saved in data/raw/primock57/confidence_drafts, so the flags are
recomputed with the current rules and no model calls.

  uv run --group voice python -m evals.voice.asr_confidence [--drafts 6]
  (DEEPGRAM_API_KEY the first time)
"""

import argparse
import json
import re
import statistics
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from agents.speech_flags import flag_statements, kept
from apps.api.auth import issue_token
from config.settings import Settings
from evals.voice.asr_eval import CONSULTATIONS, DATA, medical_terms, normalise
from evals.voice.scribe_eval import PATIENT, diarize, intervals
from voice.scribe import (
    API,
    UNSURE_BELOW,
    Word,
    assign_roles,
    group_turns,
    post_draft,
    transcript_for_api,
)

ROOT = Path(__file__).resolve().parents[2]
CACHE = DATA / "confidence_cache"
DRAFTS = DATA / "confidence_drafts"  # the drafts' de-identified transcript and statements
REPORT = ROOT / "evals" / "reports" / "voice" / "asr_confidence.md"
GRID = [round(0.30 + 0.05 * i, 2) for i in range(14)]  # 0.30 ... 0.95
MAX_FLAG_RATE = 0.05
FOLDS = (CONSULTATIONS[:3], CONSULTATIONS[3:])


@dataclass(frozen=True)
class Scored:
    consultation: str
    text: str
    confidence: float
    wrong: bool
    medical_error: bool
    reference: str  # the reference token it was aligned to ("" for an insertion)


def pairs(ref: Sequence[str], hyp: Sequence[str]) -> list[tuple[int | None, int | None]]:
    """Levenshtein alignment as (reference index, hypothesis index) pairs, in order; None marks a
    deletion (no hypothesis token) or an insertion (no reference token)."""
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
    out: list[tuple[int | None, int | None]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dist[i][j] == dist[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            out.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i > 0 and dist[i][j] == dist[i - 1][j] + 1:
            out.append((i - 1, None))
            i -= 1
        else:
            out.append((None, j - 1))
            j -= 1
    return out[::-1]


def label(
    consultation: str, words: Sequence[Word], ref: Sequence[str], medical: set[str]
) -> tuple[list[Scored], int]:
    """The scored recognised words, and the medical terms the recogniser left out entirely."""
    hyp: list[str] = []
    owner: list[int] = []
    for index, word in enumerate(words):
        for token in normalise(word.text):
            hyp.append(token)
            owner.append(index)
    wrong: dict[int, str] = {}
    medical_errors: set[int] = set()
    left_out = 0
    for i, j in pairs(ref, hyp):
        if j is None:
            left_out += i is not None and ref[i] in medical
            continue
        if i is None or ref[i] != hyp[j]:
            wrong.setdefault(owner[j], "" if i is None else ref[i])
            if hyp[j] in medical or (i is not None and ref[i] in medical):
                medical_errors.add(owner[j])
    scored = [
        Scored(
            consultation,
            word.text,
            word.confidence,
            index in wrong,
            index in medical_errors,
            wrong.get(index, ""),
        )
        for index, word in enumerate(words)
        if normalise(word.text) and not any(ch.isdigit() for ch in word.text)
    ]
    return scored, left_out


def rates(rows: Sequence[Scored], threshold: float) -> dict[str, float]:
    flagged = [r for r in rows if r.confidence < threshold]
    wrong = [r for r in rows if r.wrong]
    medical = [r for r in rows if r.medical_error]
    return {
        "flag_rate": len(flagged) / max(1, len(rows)),
        "error_recall": sum(r.wrong for r in flagged) / max(1, len(wrong)),
        "precision": sum(r.wrong for r in flagged) / max(1, len(flagged)),
        "medical_recall": sum(r.medical_error for r in flagged) / max(1, len(medical)),
        "flagged": len(flagged),
        "medical_flagged": sum(r.medical_error for r in flagged),
    }


def choose(rows: Sequence[Scored]) -> float | None:
    """The rule: the largest grid threshold that flags at most MAX_FLAG_RATE of the words."""
    fitting = [t for t in GRID if rates(rows, t)["flag_rate"] <= MAX_FLAG_RATE]
    return max(fitting) if fitting else None


def reference_tokens(consultation: str) -> list[str]:
    grids = {
        s: intervals((DATA / "transcripts" / f"{consultation}_{s}.TextGrid").read_text("utf-8"))
        for s in ("doctor", "patient")
    }
    merged = sorted((a, t) for s in grids for a, _, t in grids[s])
    return normalise(" ".join(t for _, t in merged))


def bare(text: str) -> str:
    return re.sub(r"^\W+|\W+$", "", text).lower()


def made_draft(consultation: str, words: list[Word], token: str) -> dict[str, Any] | None:
    """The de-identified transcript, statements and unsure words of one draft from the listener's
    turns, saved so the flags can be recomputed with no model calls; None if no draft came back."""
    path = DRAFTS / f"{consultation}.json"
    if path.exists():
        saved: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return saved
    turns = group_turns(words)
    try:
        out = post_draft(transcript_for_api(turns, assign_roles(turns)), PATIENT, token)
    except httpx.HTTPStatusError as exc:
        print(f"  {consultation}: no draft ({exc.response.status_code})", flush=True)
        return None
    httpx.post(  # an evaluation draft: rejected, so it does not wait in the doctor's list
        f"{API}/v1/drafts/{out['draft_id']}/review",
        json={"decision": "reject", "reason": "evaluation draft (asr_confidence)"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    ).raise_for_status()
    draft = {
        "transcript": out["transcript"],
        "statements": out["draft"]["statements"],
        "unsure": out["unsure_speech"]["turns"],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(draft), encoding="utf-8")
    return draft


def draft_flags(
    consultation: str, words: list[Word], wrong: set[str], token: str
) -> dict[str, Any]:
    """What the review flags on one draft, by the current rules; `wrong` holds the unsure words
    that were recognition errors somewhere in the consultation."""
    draft = made_draft(consultation, words, token)
    if draft is None:
        return {"name": consultation, "ok": False, "error": "no draft"}
    transcript = draft["transcript"]
    unsure = [kept(u, t) for u, t in zip(draft["unsure"], transcript, strict=True)]
    flags = flag_statements(draft["statements"], transcript, unsure)
    heard = {u["word"].lower() for f in flags for u in f["heard"]}
    return {
        "name": consultation,
        "ok": True,
        "turns": len(transcript),
        "unsure": sum(len(turn) for turn in unsure),
        "statements": len(flags),
        "heard": sum(bool(f["heard"]) for f in flags),
        "changed": sum(f["changed"] is not None for f in flags),
        "heard_words": sorted(heard),
        "heard_wrong": sorted(heard & wrong),
        "terms": sorted({t for f in flags if f["changed"] for t in f["changed"]["terms"]}),
    }


def draft_lines(drafts: list[dict[str, Any]]) -> list[str]:
    lines = ["", "## On the drafts", ""]
    lines += [
        "| consultation | turns | unsure words kept | statements | flagged: heard / changed "
        "| words shown (recognition errors) | terms not in the cited speech |",
        "|---|---|---|---|---|---|---|",
    ]
    for d in drafts:
        if not d["ok"]:
            lines.append(f"| {d['name']} | | | failed: {d['error']} | | | |")
            continue
        shown = ", ".join(
            w + (" (error)" if w in d["heard_wrong"] else "") for w in d["heard_words"]
        )
        lines.append(
            f"| {d['name']} | {d['turns']} | {d['unsure']} | {d['statements']} | "
            f"{d['heard']} / {d['changed']} | {shown or '-'} | {', '.join(d['terms']) or '-'} |"
        )
    ok = [d for d in drafts if d["ok"]]
    lines += [
        "",
        f"{len(ok)} of {len(drafts)} drafts produced (patient {PATIENT}, then rejected); "
        f"{sum(d['heard'] for d in ok)} statements flagged heard and "
        f"{sum(d['changed'] for d in ok)} changed, of {sum(d['statements'] for d in ok)}. A word "
        "counts as a recognition error when an unsure instance of it was wrong against the "
        "reference. Function words are not shown: in a first run they were most of the flags "
        "(38 of 100 statements flagged, mostly for 'a', 'and', 'to', 'is').",
    ]
    return lines


def report(
    rows: list[Scored], left_out: int, chosen: float | None, drafts: list[dict[str, Any]]
) -> str:
    wrong = [r for r in rows if r.wrong]
    right = [r for r in rows if not r.wrong]
    lines = [
        "# Low-confidence speech: what a confidence threshold catches (ADR-0027)",
        "",
        f"PriMock57, {len(CONSULTATIONS)} consultations, doctor and patient channels mixed and "
        "streamed through the Scribe listener (Deepgram nova-3-medical live, diarization and "
        "numerals on). Generated by `evals/voice/asr_confidence.py`. "
        f"{len(rows):,} scored words, {len(wrong):,} wrong "
        f"({len(wrong) / max(1, len(rows)):.1%}; words with digits and fillers not scored); "
        f"median confidence {statistics.median(r.confidence for r in right):.3f} for right words, "
        f"{statistics.median(r.confidence for r in wrong):.3f} for wrong ones.",
        "",
        "**Rule (written before the run):** the largest threshold on the grid that flags at "
        f"most {MAX_FLAG_RATE:.0%} of the words, chosen on one half of the consultations and "
        "measured on the other; the listener uses the one chosen on all six.",
        "",
        "| flag words under | flagged | errors caught | flagged that were wrong "
        "| medical errors caught |",
        "|---|---|---|---|---|",
    ]
    for t in GRID:
        r = rates(rows, t)
        mark = " **(chosen)**" if t == chosen else ""
        lines.append(
            f"| {t:.2f}{mark} | {r['flag_rate']:.1%} | {r['error_recall']:.1%} | "
            f"{r['precision']:.1%} | {r['medical_flagged']} of "
            f"{sum(x.medical_error for x in rows)} |"
        )
    lines += ["", "## Held out (2-fold over consultations)", ""]
    lines += [
        "| chosen on | threshold | measured on | flagged | errors caught | medical errors caught |",
        "|---|---|---|---|---|---|",
    ]
    for train, test in (FOLDS, FOLDS[::-1]):
        fold = choose([x for x in rows if x.consultation in train])
        held = [x for x in rows if x.consultation in test]
        if fold is None:
            lines.append(f"| {', '.join(train)} | none fits | {', '.join(test)} | | | |")
            continue
        h = rates(held, fold)
        lines.append(
            f"| {', '.join(train)} | {fold:.2f} | {', '.join(test)} | {h['flag_rate']:.1%} | "
            f"{h['error_recall']:.1%} | {h['medical_flagged']} of "
            f"{sum(x.medical_error for x in held)} |"
        )
    lines += ["", "## Medical errors", ""]
    lines += [
        "| consultation | heard | said | confidence | flagged |",
        "|---|---|---|---|---|",
    ]
    for row in sorted((x for x in rows if x.medical_error), key=lambda x: x.confidence):
        flagged = "yes" if chosen is not None and row.confidence < chosen else "no"
        lines.append(
            f"| {row.consultation} | {row.text} | {row.reference or '(nothing)'} | "
            f"{row.confidence:.3f} | {flagged} |"
        )
    lines += [
        "",
        f"Medical terms the recogniser left out entirely (no word to highlight): {left_out}.",
        "",
        "Notes: six consultations, one recording set-up (two close-talk microphones mixed), so the "
        "numbers are indicative. Errors are against the reference transcript, which spells "
        "numbers, uses UK spellings (diarrhoea) and orders overlapping speech approximately, so "
        "some listed medical errors are spelling variants or alignment slips. The listener's "
        f"threshold is `voice/scribe.py` `UNSURE_BELOW` = {UNSURE_BELOW}.",
    ]
    if drafts:
        lines += draft_lines(drafts)
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--drafts", type=int, default=0, help="consultations to draft")
    args = parser.parse_args(argv)
    medical = medical_terms()
    token = issue_token("dr-demo", Settings().auth_token_key)
    rows: list[Scored] = []
    drafts: list[dict[str, Any]] = []
    left_out = 0
    for index, consultation in enumerate(CONSULTATIONS):
        words = diarize(consultation, CACHE)
        scored, missing = label(consultation, words, reference_tokens(consultation), medical)
        rows += scored
        left_out += missing
        print(f"{consultation}: {len(scored)} scored, {sum(r.wrong for r in scored)} wrong")
        if index < args.drafts:
            wrong = {bare(r.text) for r in scored if r.wrong and r.confidence < UNSURE_BELOW}
            drafts.append(draft_flags(consultation, words, wrong, token))
            print(f"  draft: {drafts[-1]}", flush=True)
    chosen = choose(rows)
    REPORT.write_text(report(rows, left_out, chosen, drafts), encoding="utf-8", newline="\n")
    print(f"chosen threshold: {chosen}; listener uses {UNSURE_BELOW}; wrote {REPORT}")
    return 0 if chosen == UNSURE_BELOW else 1


if __name__ == "__main__":
    sys.exit(main())
