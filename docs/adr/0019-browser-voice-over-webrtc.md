# ADR-0019: Browser voice over WebRTC with a self-hosted LiveKit server

Status: Proposed · Date: 2026-10-26

## Context

SPEC §4: both voice pipelines "run as LiveKit Agents workers; audio travels over WebRTC through a
LiveKit server". Until now the agent ran only in LiveKit's console mode (local microphone and
speakers on the machine running the agent), so there was no browser client, no WebRTC transport
and no LiveKit server; the README listed this as a limitation. The agent itself already worked as
a worker for rooms (`agent_cascaded.py dev|start`), and `just gen-keys` already generated LiveKit
keys.

## Options

1. **LiveKit Cloud** (free tier): no server to run, but a new processor that receives the doctor's
   raw audio (a BAA question, like the speech vendors), and an account.
2. **Self-hosted LiveKit server** (Apache-2.0) in Docker Compose: local, no new processor.
3. **Pipecat with a transport such as Daily**: a different framework from the agent's (ADR-0010).

## Decision

Option 2.

- `livekit` service (`livekit/livekit-server:v1.13.9`, profile `voice`, 256 MB limit), ports on
  127.0.0.1 only, WebRTC media on one UDP port (7882) with TCP 7881 as a fallback, ICE candidates
  on 127.0.0.1 (`infra/livekit/livekit.yaml`); key and secret from `.env` (`LIVEKIT_KEYS`).
- `POST /v1/voice/token` (doctors only, audited as `voice.session`): a room per session and a
  15-minute HS256 room token signed with the LiveKit secret (`apps/api/voice_token.py`, written
  directly rather than adding a package to the API image).
- The agent worker (`just voice dev`, or `start`) joins every new room. After each answer it sends
  the question, the cited sentences and each source's title, section and link on the room's data
  channel (`clinscribe.answer`; no source text), so "sources are on screen" is literally true.
- The review UI's Voice tab (`livekit-client` 2.22.4, loaded only when the tab opens) joins the
  room with the browser's echo cancellation, noise suppression and gain control, plays the agent,
  shows the live transcript and each answer's citations. A refused microphone keeps the session
  (the doctor can still listen) and says why.

## Consequences

- Shown end to end without a browser (`voice/webrtc_check.py`, `evals/reports/voice/webrtc.md`): a
  Python LiveKit client in the doctor's place got a token from the API, joined, heard the greeting,
  played 10 recorded questions; the agent joined in 1.7 s, replied aloud to 9 and sent 8 cited
  answers on the data channel; time to first audio at the client p50 6.8 / p95 16.9 s, slower than
  the in-process measurement (4.3 / 7.1 s on 2026-10-19), which leaves out the wait for the end of
  the turn and the network. In the browser pane: connect, agent present, greeting transcript and a
  live agent audio track; the pane blocks microphones, so speech from a browser was not tried here.
- No new processor: audio stays on the machine until the agent sends it to Deepgram, as before.
  LiveKit adds 69 MiB; the stack with the voice profile measured 5.55 GiB.
- Only for one machine: ICE uses 127.0.0.1 and no TURN server is configured, so a browser on
  another device cannot connect. A deployment needs a public IP or TURN, TLS (wss) and per-user
  agent credentials: the worker calls the API with the demo doctor's token, not the token of the
  doctor in the room.
- The voice answers stay in surrogate form (ADR-0015).
