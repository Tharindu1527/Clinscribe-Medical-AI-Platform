# Demo video

- **File:** `.artifacts/demo/clinscribe_demo.mp4` (git-ignored): 3 min 37 s, 1920×1080, H.264 + AAC,
  12.6 MB, recorded 2026-10-18.
- **Link:** _to be added after upload (YouTube, unlisted)_.
- **Made with:** `just demo-video` (`scripts/demo_video.py`). The script drives the review UI in a hidden
  Chrome (Playwright, the installed browser), records it with the DevTools screencast and assembles frames
  and audio with ffmpeg. Measured values of the run: `.artifacts/demo/timeline.json`.

## What is live and what is not

| Live (calls to the running stack during the recording) | Synthetic, and said so on screen |
|---|---|
| Speech recognition (Deepgram nova-3-medical, streamed), `/v1/ask`, the spoken answer (Cartesia sonic-2) | The doctor's voice: Cartesia speech streamed into the voice steps, because a script cannot speak into a microphone |
| Ask in the UI (agentic path, DDInter facts), the cited answer and its sources | The narrator (Cartesia) |
| Scribe: the note writer, guardrails, the refused write, the approved FHIR write | Patient and consultation (Synthea patient 1617; a made-up transcript) |
| The audit log as admin | Waits over 6 s are compressed to 2.5 s; the real elapsed time is on screen |

## Scenes

| Time | Scene | Shown |
|---|---|---|
| 0:00 | Title, architecture | modes; voice → de-ID → LangGraph agent → MCP tools → LiteLLM gateway |
| 0:33 | Voice question | "What is the usual starting dose of warfarin?" → transcript → cited answer (fast path) → spoken answer; time per stage |
| 1:20 | Ask in the review UI | "Does clarithromycin interact with warfarin?" → agentic path, three cited sentences, sources with passages |
| 1:50 | Scribe | draft with statements flagged "no guideline source"; wrong family name → write refused; new draft, correct identifiers → `Saved to FHIR: DocumentReference/60565` |
| 2:45 | Audit log (admin) | the run's asks, drafts, refused write and approved write, with model and prompt version |
| 2:58 | Results, end card | measured results, including the voice latency budget not met |

Voice stages in this run (one turn, so no percentiles): end of speech → final transcript 1,128 ms
(endpointing included), Ask 2,775 ms, first audio byte 1,842 ms, **time to first audio 5,745 ms** against
the 1,500 ms budget. Over 30 questions the p50 / p95 are 3,545 / 19,732 ms (`evals/reports/voice/latency.md`).

## Not shown

- **Scribe from live consultation audio.** SPEC §14 asks for "a live voice consultation through to an
  approved FHIR note". In the video the voice part is a spoken question (Ask), and Scribe starts from a
  pasted transcript: ambient capture with speaker diarization into the note writer is not built.
- Lab mode, failover (`just gate 5`), the browser WebRTC client (not built; the console agent is `just voice`).

## Re-record

`just up rag`, `npm --prefix apps/web run dev`, `DEV_LOGIN=true` in `.env`, then `just demo-video`
(about 6 minutes; `--scenes title,results` records a subset). Narration audio is cached in
`.artifacts/demo/tts/`, so a re-recording only pays for the live calls: two Ask turns, two drafts and
one spoken answer.
