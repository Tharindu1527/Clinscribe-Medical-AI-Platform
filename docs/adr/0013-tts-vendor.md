# ADR-0013: Text-to-speech for the voice agent — Deepgram Aura-2

Status: Proposed · Date: 2026-10-19

## Context

The voice agent spoke with Cartesia sonic-2 (free tier). On 2026-10-18 Cartesia answered HTTP 402
(free-tier credit used up: question audio for the evals, the demo narration and the agent's answers),
so `just voice` could transcribe and answer but not speak. SPEC §4 lists Cartesia or ElevenLabs.

## Options

1. **Wait for Cartesia's monthly credit**, or pay for a plan. Fastest first byte measured (below).
2. **ElevenLabs free tier**: a new account and key; not measured.
3. **Deepgram Aura-2**: the same vendor and key as speech recognition (free credit in place), a
   LiveKit plugin (`deepgram.TTS`), 41 English voices.

Measured with the same pipeline and questions (`evals/voice/latency_eval.py`, 30 golden questions,
the answer's first sentence synthesized, streaming):

| | TTS first byte p50 / p95 |
|---|---|
| Cartesia sonic-2 (2026-10-14) | 812 / 1,301 ms |
| Deepgram Aura-2 `aura-2-orpheus-en` (2026-10-19) | 1,413 / 1,550 ms |

## Decision

Option 3 for now: `deepgram.TTS(model="aura-2-orpheus-en")` in `voice/agent_cascaded.py`; the
evals and the demo script use Aura voices too. It adds ~600 ms at p50 to time to first audio, which
already misses its 1.5 s budget for other reasons (the cited answer), and it removes one vendor.

## Consequences

- One line to switch back when Cartesia's credit returns (the LiveKit plugin is removed from
  `voice/pyproject.toml`; re-add `cartesia` to the extras).
- Deepgram now receives the spoken answer text as well as the doctor's audio: still one vendor to
  cover by a BAA (`docs/compliance/baa_vendor_matrix.md`).
- The voice smoke test (`just gate 4`) now synthesizes the answer with the production voice, so a
  TTS vendor that stops working fails the gate instead of the demo.
- Time to first audio after the switch (2026-10-19, 29 of 30 turns answered): p50 4,296 / p95
  7,093 ms (`evals/reports/voice/latency.md`); the earlier run's p95 (19.7 s) was the agentic Ask tail,
  which was shorter in this run.
