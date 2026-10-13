# ADR-0010: Voice framework — LiveKit Agents

Status: Proposed · Date: 2026-10-14

## Context

The voice layer (SPEC §4) needs streaming STT and TTS, voice activity and end-of-turn detection,
barge-in with history truncation, WebRTC transport with browser echo cancellation, and per-stage
timing. The answer itself must come from ClinScribe's Ask graph (de-ID, retrieval, citations,
guardrails), not from a model the framework calls directly.

## Options

1. **LiveKit Agents 1.8.3** (Apache-2.0): agent workers joined to WebRTC rooms on a LiveKit server;
   plugins for Deepgram, Cartesia, Silero VAD and an English end-of-turn model; console mode for local
   microphone tests; `Agent.llm_node` can be replaced.
2. **Pipecat 1.12** (BSD-2-Clause): a frame pipeline (transport → STT → LLM → TTS) with many service
   integrations and several transports (WebRTC via Daily or SmallWebRTC, websockets).
3. **Own pipeline** on the vendors' websockets (as `evals/voice/latency_eval.py` does for measuring).

## Decision

Option 1. The deciding facts, checked in the installed package (`voice/`, 89 packages, isolated):

- `Agent.llm_node` accepts an async iterator of plain strings, so the ClinScribe API answers the
  question and the framework only speaks it (`voice/agent_cascaded.py`; smoke-tested: the cited
  warfarin answer spoken back in 3.7 s). Guardrails and citations stay in one place.
- End-of-turn detection beyond silence (a local English turn model) and interruption handling with
  history truncation are built in; both modes are selectable (`VOICE_TURN=semantic|vad`).
- Console mode runs the full pipeline on a laptop without a LiveKit server, which is how the demo is
  recorded.

Pipecat was compared on its documented design, not built: it would serve equally well (its frame
pipeline also allows a custom LLM step), and SPEC §10 lists it only as a comparison. Not building it
is a scope cut for the deadline.

## Consequences

- LiveKit Agents pins `opentelemetry < 1.45` while the main project uses 1.45, so the agent lives in
  its own uv project (`voice/pyproject.toml`) and talks to ClinScribe only over HTTP.
- Browser use needs a LiveKit server (a `voice` Compose profile) and a token endpoint; not built yet.
  Console mode covers the demo; WebRTC echo cancellation is then the operating system's.
- Speech vendors receive raw audio before de-identification (SPEC §8): a BAA-covered vendor or a
  self-hosted recogniser is required for real use (`docs/compliance/baa_vendor_matrix.md`).
