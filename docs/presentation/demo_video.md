# Demo video

- **File:** `.artifacts/demo/clinscribe_demo.mp4` (git-ignored): 4 min 51 s, 1920×1080, H.264 + AAC,
  20.3 MB, recorded 2026-10-18.
- **Link:** _to be added after upload (YouTube, unlisted)_.
- **Made with:** `just demo-video` (`scripts/demo_video.py`). The script drives the review UI in a hidden
  Chrome (Playwright, the installed browser), records it with the DevTools screencast and assembles frames
  and audio with ffmpeg. Measured values of the run: `.artifacts/demo/timeline.json`.

## What is live and what is not

| Live (calls to the running stack during the recording) | Not live, and said so on screen |
|---|---|
| Voice question: Deepgram nova-3-medical (streamed), `/v1/ask`, the spoken answer (Cartesia sonic-2) | The question's voice: Cartesia speech streamed in, because a script cannot speak into a microphone |
| Ask in the UI (agentic path, DDInter facts), the cited answer and its sources | The narrator (Cartesia) |
| Scribe: the consultation audio streamed into the listener (`voice/scribe.py`): live transcription with diarization, roles, de-ID, note writer, guardrails, the refused write, the approved FHIR write | The consultation is a PriMock57 recording (role-played, real voices, CC BY 4.0) played into the listener; its draft is filed under Synthea patient 1617 |
| The audit log as admin | Waits over 6 s are compressed to 2.5 s, with the real time on screen; after the first 32 s of the consultation, the rest is streamed at 2x and shown compressed |

The UI's demo sign-in is answered by the script with a locally issued token for the synthetic users, so
the API keeps `DEV_LOGIN=false`.

## Scenes

| Time | Scene | Shown |
|---|---|---|
| 0:00 | Title, architecture | modes; voice → de-ID → LangGraph agent → MCP tools → LiteLLM gateway |
| 0:37 | Voice question | "What is the usual starting dose of warfarin?" → transcript → cited answer (fast path) → spoken answer; time per stage |
| 1:15 | Ask in the review UI | "Does clarithromycin interact with warfarin?" → agentic path, cited sentences, sources with passages |
| 1:47 | Scribe from audio | PriMock57 day3_consultation02: live diarized transcript (the patient's name, birth date and address are said in the first 30 s) → roles (speaker 0 doctor, speaker 1 patient, 57 turns) → draft (24 statements, 5 flagged "no guideline source"; name, birth date, address and postcode as `PERSON_2`, `DATE_1`, `STREET_ADDRESS_1`, `ZIP_1`) → opened from "Drafts awaiting review" → wrong family name **refused** → drafted again, correct identifiers → `Saved to FHIR: DocumentReference/60879` |
| 4:00 | Audit log (admin) | the run's actions, with model and prompt version |
| 4:08 | Results, end card | measured results, including the voice latency budget not met |

Voice stages in this run (one turn, so no percentiles): end of speech → final transcript 1,213 ms
(endpointing included), Ask 4,628 ms, first audio byte 1,253 ms, **time to first audio 7,094 ms** against
the 1,500 ms budget. Over 30 questions the p50 / p95 are 3,545 / 19,732 ms (`evals/reports/voice/latency.md`).

## Found while making it

- An earlier take used two synthetic TTS voices for the consultation: Deepgram's diarization (live and
  batch) did not tell them apart, so the take uses a real recording.
- An earlier take's draft showed the spoken birth date ("21 12 at 1986") and the spelled-out postcode
  ("N W 36 P Q") unredacted: the de-ID patterns did not know these forms. Fixed (PROGRESS, 2026-10-18)
  before this take.

## Not shown

Lab mode, failover (`just gate 5`), the browser WebRTC client (not built; the console agent is `just voice`).

## Re-record

`just up rag`, `npm --prefix apps/web run dev`, then `just demo-video` (about 10 minutes; `--scenes
title,results` records a subset). Narration audio is cached in `.artifacts/demo/tts/`, so a re-recording
pays only for the live calls: two Ask turns, about 7 minutes of streamed audio, two drafts and one spoken
answer.
