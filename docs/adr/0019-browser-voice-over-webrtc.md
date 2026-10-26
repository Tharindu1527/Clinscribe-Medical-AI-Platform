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
  played 10 recorded questions; in the first run the agent joined in 1.7 s, replied aloud to 9
  and sent 8 cited answers on the data channel; time to first audio at the client p50 6.8 / p95 16.9 s, slower than
  the in-process measurement (4.3 / 7.1 s on 2026-10-19), which leaves out the wait for the end of
  the turn and the network. In the browser pane: connect, agent present, greeting transcript and a
  live agent audio track; the pane blocks microphones, so speech from a browser was not tried here.
- No new processor: audio stays on the machine until the agent sends it to Deepgram, as before.
  LiveKit adds 69 MiB; the stack with the voice profile measured 5.55 GiB.
- Only for one machine: ICE uses 127.0.0.1 and no TURN server is configured, so a browser on
  another device cannot connect. A deployment needs a public IP or TURN and TLS (wss).
- First version: the worker called the API with the demo doctor's token, so every voice question
  was audited as `dr-demo`, whoever was in the room. Fixed the same day (below).
- The voice answers stay in surrogate form (ADR-0015).

## Update 2026-10-26: the agent asks as the doctor in its room

SPEC §2 story 5 and §8 ("who did what, when") need the audit log to name the doctor who asked a
spoken question. Options: (a) the browser sends the doctor's API token to the agent over the data
channel (the token then passes through LiveKit and every room participant could read it);
(b) the agent gets its own role that may call `/v1/ask` (the log would name the agent, not the
doctor); (c) **delegation**: the worker holds a service key (`VOICE_AGENT_KEY`, from
`just gen-keys`) and, when a participant joins, asks `POST /v1/voice/delegate` for a 30-minute API
token for that participant. Chosen: (c).

- The API gives a token only if the key matches (constant-time compare), the user is a doctor and
  the room is one it issued to that doctor (`clinscribe-<user>-<8 hex>`, the name `/v1/voice/token`
  creates). LiveKit has already checked the participant's identity against the room token the API
  signed, so the identity cannot be chosen by the browser. Each delegation is audited
  (`voice.delegate`, with the room).
- Fails closed: a refused or failed delegation leaves the agent without a token; it says that it
  could not confirm who is asking and sends nothing to the API. Console mode (`just voice`) keeps
  the local demo doctor's token.
- Measured (`just voice-webrtc dr-second`, `evals/reports/voice/webrtc.md`): 10 questions as the
  second synthetic doctor, 10 cited answers, audit rows `ask by dr-second` ×10 and
  `voice.delegate by dr-second` ×1, none as `dr-demo`; time to first audio at the client p50 6.7 /
  p95 7.9 s. With a wrong service key the API refused (403), the agent answered 0 of 2 questions
  and no `ask` row was written. Unit tests: wrong, missing and unset key; another doctor's room; a
  non-doctor; a room name the API never issues.
- Limits: the worker trusts the first participant who joins (the room is issued to one doctor and
  LiveKit admits only holders of its token); a stolen service key could mint doctor tokens for
  rooms named after any doctor, so the key is a secret like `AUTH_TOKEN_KEY` and lives only in
  `.env`.
