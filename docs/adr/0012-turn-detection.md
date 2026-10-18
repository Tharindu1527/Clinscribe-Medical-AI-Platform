# ADR-0012: Turn detection for voice questions — semantic model, transcript punctuation off

Status: Proposed · Date: 2026-10-18

## Context

SPEC §4 builds two turn-detection strategies (Silero VAD silence only, and LiveKit's English
end-of-turn model) and asks for the false cut-off rate and the delay each adds. A clinician who
pauses mid-sentence ("What blood pressure target is recommended for ... people with diabetes?") and
is cut off gets an answer to half a question: a wasted Ask call (2-20 s), and the rest of the
sentence then arrives as a fragment of its own.

Measured with `voice/turn_eval.py` on the production session (LiveKit 1.8.3, Deepgram nova-3-medical,
simulated sound card, synthetic speech): 12 clinical questions, each spoken whole and with a 0.7,
1.2 and 2.0 s pause inside the sentence (`evals/reports/voice/turn_taking.md`).

## Options

| | Cut off in the pause (of 36) | End of turn on whole questions |
|---|---|---|
| 1. VAD only | 27 (4, 11, 12 at 0.7 / 1.2 / 2.0 s) | p50 771 / p95 904 ms |
| 2. Semantic model, punctuation on (the LiveKit plugin's default) | 10 (2, 4, 4) | p50 787 / p95 857 ms |
| 3. Semantic model, punctuation off | **1** (0, 1, 0) | p50 905 / p95 3,107 ms: 8 of 12 at 0.7-0.9 s, 4 of 12 at ~3 s |

With punctuation on, Deepgram ended the partial transcripts with a question mark ("... recommended
for?", "... given for?", "... a child with?") and the end-of-turn model took them as finished
questions: the same 4 questions caused all 10 cut-offs. Without punctuation the model is unsure on
some whole questions and waits for the 3 s maximum endpointing delay. (The plugin's docstring says the
turn detector works better with punctuation; on these mid-sentence pauses it did not.)

## Decision

Option 3 for the voice agent: `deepgram.STT(..., punctuate=False)` in `agent_cascaded.build_session`.
A cut-off produces a wrong answer; the cost of option 3 is about 2 s of extra waiting on a third of
the questions, against a turn that already takes 3.5 s to the first audio (p50).

## Consequences

- One parameter; `just voice-turns --parts cutoffs --turns semantic,semantic-nopunct` re-measures both.
- Not tried: a shorter maximum endpointing delay with punctuation off (it would trade some of the
  3 s waits back for cut-offs at long pauses), or the multilingual turn model.
- The barge-in and echo results in the report were measured with punctuation on; both depend on
  voice activity, not on the transcript.
- Synthetic speech, one voice, 12 questions: a test with real speakers and real pauses is still to
  do.
