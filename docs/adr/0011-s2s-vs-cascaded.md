# ADR-0011: Speech-to-speech vs cascaded voice — cascaded by default

Status: Proposed · Date: 2026-10-14

## Context

SPEC §4 builds two voice paths behind `VOICE_MODE` and compares latency, quality and privacy:
cascaded (STT → ClinScribe Ask → TTS) and speech-to-speech (a realtime model that hears audio and
speaks audio; Gemini Live on the free tier, OpenAI Realtime in this ADR only).

## Options

1. **Cascaded** (Deepgram nova-3 → `/v1/ask` → Cartesia sonic-2), `voice/agent_cascaded.py`.
2. **Speech-to-speech**, Gemini Live (`gemini-2.5-flash-native-audio-latest`).
3. **OpenAI Realtime** (not run: no free tier; same trade-offs as option 2).

Measured on 2026-10-14 with the same synthetic question audio (golden questions spoken by Cartesia),
streamed at real-time pace from this laptop:

| | Cascaded | Speech-to-speech (Gemini Live) |
|---|---|---|
| TTFA p50 / p95 | 3,545 / 19,732 ms (all 30 turns); fast path 3,276 / 5,577 ms | 3,493 / 6,137 ms (10 turns) |
| Answer grounded in retrieved guidelines, every sentence cited | yes (cite or abstain) | no |
| Guardrails before speaking (doses, diagnosis wording, injection) | yes | no (audio out cannot be checked before it plays) |
| De-identification before the model | yes (transcript de-identified; STT vendor hears audio) | no (the model provider hears raw audio) |
| Text for the audit log and the screen | yes | transcripts only if requested; not the source of the answer |
| Calls through the LiteLLM gateway | yes | no (no audio-to-audio route; direct provider call) |

Reports: `evals/reports/voice/latency.md`, `evals/reports/voice/s2s_latency.md`.

## Decision

Cascaded is the default for every clinical use. Speech-to-speech was **not faster** here: its
p50 equals the cascaded fast path, and its p95 is only better than the cascaded agentic tail. It
gives up every control that makes an answer safe to act on. Speech-to-speech stays a measured option
for non-clinical small talk (greetings, "please repeat"), and only with a BAA-covered provider.

## Consequences

- Neither path meets the SPEC budget (TTFA p95 < 1.5 s). The cascaded bottleneck is the Ask step
  (non-streamed cited answer, agentic tail); fixes are listed in `evals/reports/voice/latency.md`
  (stream the first cited sentence, keep voice on the fast path, lower reasoning effort).
- `VOICE_MODE=s2s` is a measurement script (`evals/voice/s2s_eval.py`), not a production agent; the
  production agent is cascaded only.
- The speech-to-speech measurement is the documented exception to "every model call goes through
  the gateway" (CLAUDE.md): synthetic audio, no PHI, evaluation only.
