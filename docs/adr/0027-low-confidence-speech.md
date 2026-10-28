# ADR-0027: Show the doctor what the speech recogniser was unsure of

Status: Proposed · Date: 2026-10-28

## Context

SPEC section 4 says "low-confidence drug names are highlighted for the doctor, never silently
corrected"; section 5 that the review screen "highlights statements without a source and
low-confidence ASR words"; section 8 lists "misheard drug name" as a patient-safety hazard with
"keyterm boosting; low-confidence words highlighted" as its control. Keyterm boosting was measured
in Phase 4 and gave no gain (`evals/reports/voice/asr_wer.md`); the highlight was never built. The
Scribe listener dropped Deepgram's per-word confidence, so on the review screen a word the
recogniser guessed looked the same as one it heard clearly, and the note writer, which sees only
text, could turn a guess into a confident clinical statement.

## Options

1. **Leave it to the doctor's reading** of the note (status quo).
2. **Highlight words under a confidence threshold** in the transcript and on the statements that
   rely on them; the threshold chosen by measurement.
3. **Ask the note writer to mark uncertain words**: the model never sees the confidences, and it
   would need them in the prompt (a new prompt version, and the model deciding what to show).
4. **Correct low-confidence words automatically** (lexicon lookup, a second recogniser): the SPEC
   rules it out ("never silently corrected"), and a wrong correction is the hazard itself.

## Decision

Option 2.

- **Listener** (`voice/scribe.py`): keeps each word's confidence; a turn sends the words under
  `UNSURE_BELOW` with it (`unsure`, word and confidence), and each part of a split turn the ones in
  that part.
- **Threshold**: chosen by a rule written before the measurement (`evals/voice/asr_confidence.py`):
  the largest value on a 0.30–0.95 grid that flags at most 5% of the words, chosen on three
  PriMock57 consultations and measured on the other three, both ways; the listener uses the value
  chosen on all six. Result (`evals/reports/voice/asr_confidence.md`; 7,419 scored words, 739 of
  them wrong, 10.0%; median confidence 0.998 for right words, 0.936 for wrong ones): **0.65**,
  which flags 4.4% of the words and catches 18.1% of the errors; 40.9% of the flagged words were
  wrong, four times the base rate. Held out: chosen on the first three consultations (0.65), it
  flags 3.9% of the other three's words and catches 16.5% of their errors; chosen on the last three
  (0.70), 6.3% and 24.0%. Of 16 medical-term errors (some of them spelling variants such as
  diarrhea / diarrhoea, or alignment slips) it catches 3.
- **API** (`apps/api/clinical.py`, `agents/speech_flags.py`): after de-identification, only the
  unsure words still in the de-identified turn are kept (a word de-ID replaced was PHI, and its flag
  would put the original into the saved draft); they are checkpointed with the draft. The draft
  responses carry `unsure_speech`: per turn the unsure words, and per statement two kinds of flag:
  - *heard*: the statement uses an unsure word of a turn it cites;
  - *changed*: the statement names a drug or clinical term (single words of 5+ letters from the
    RxNorm lexicon) that none of its cited turns says, while one of them had an unsure word: the
    note writer may have corrected what the recogniser heard.
  The audit row of `draft.create` counts the unsure words and the flagged statements.
- **Function words** ("a", "and", "to"; the retrieval stopword list, which keeps negations) are
  not kept: they said nothing about the note (see Consequences).
- **Review screen**: a banner with the number of flagged statements, a dashed border and a tag on
  each ("unsure speech: 'lisinopril'", or "check: hydroxyzine not in the cited speech"), the
  confidence in the tooltip, and the unsure words in each turn's tooltip. Nothing is changed or
  hidden; approval works as before.

## Consequences

- On the drafts (`--drafts 6`: the real note writer on the listener's turns; the 96-turn
  consultation gave no draft, the known output limit), **26 of 118 statements were flagged heard,
  none changed**. One flag is the hazard itself: the doctor said "Bell's palsy", the recogniser
  wrote "valve palsy" (confidence 0.57), and the note said "the symptoms might be valve palsy".
  Other flagged words were heard right ("asthma", "dioralyte", "polyps") or are generic
  ("taking", "after"). A first run also flagged function words, 38 of 100 statements, mostly for
  "a", "and", "to"; those are now left out (the retrieval stopword list, which keeps "no" and
  "not"), a rule added after seeing that run.
- Confidence is a weak signal: about four in five recognition errors carry a confidence above the
  threshold. The flag asks the doctor to check a statement; it does not certify the others, and the
  note still has to be read against the consultation. A higher threshold (0.80: 9.6% of words,
  31.8% of errors) is the lever if doctors want more recall for more checking.
- The drafts run found postmortem 0005 (de-ID workers killed by uvicorn's 5 s health check, 2 of
  6 drafts failed): fixed before the numbers above, which had no worker deaths.
- The note writer's prompt is unchanged: it never sees confidences, so a misheard word reaches
  the note as text and the flag is the doctor's only signal. Telling the model would need a new
  prompt version and an answer evaluation (ADR-0026).
- The "changed" rule uses the de-ID clinical lexicon, which also holds a few everyday words
  ("water", "today"); entries under five letters are left out, and a flag needs the term to be
  absent from the cited turns, so an everyday word rarely triggers it. It is unit-tested but not
  measured on a real correction: the five evaluation drafts had none (the note writer copied what
  it heard, "valve palsy" included).
- Typed transcripts (the review UI's text box) carry no confidences and get no flags. Voice Ask is
  not covered: the spoken question goes to the answer as it was heard (ADR-0018's subject check
  abstains when a misheard drug name matches nothing in the corpus).
- Drafts made before this change show no flags (they have no unsure words saved).
