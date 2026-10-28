# Demo video

- **File:** `.artifacts/demo/clinscribe_demo.mp4` (git-ignored): 5 min 13 s, 1920×1080, H.264 + AAC,
  21.4 MB, recorded 2026-10-29 on the redesigned review UI (Deepgram Aura voices). The previous take
  (2026-10-19, the old UI, 4 min 50 s) is kept beside it as `old-ui-2026-10-19_clinscribe_demo.mp4`.
- **Link:** _to be added after upload (YouTube, unlisted)_.
- **Made with:** `just demo-video` (`scripts/demo_video.py`). The script drives the review UI in a hidden
  Chrome (Playwright, the installed browser), records it with the DevTools screencast and assembles frames
  and audio with ffmpeg. Measured values of the run: `.artifacts/demo/timeline.json`.

## What is live and what is not

| Live (calls to the running stack during the recording) | Not live, and said so on screen |
|---|---|
| Voice question: Deepgram nova-3-medical (streamed), `/v1/ask`, the spoken answer (Deepgram Aura-2, the agent's voice) | The question's voice: Deepgram Aura speech streamed in, because a script cannot speak into a microphone |
| Ask in the UI (agentic path, DDInter facts), the cited answer and its sources | The narrator (Deepgram Aura) |
| Scribe: the consultation audio streamed into the listener (`voice/scribe.py`): live transcription with diarization, roles, de-ID, note writer, guardrails, the refused write, the approved FHIR write | The consultation is a PriMock57 recording (role-played, real voices, CC BY 4.0) played into the listener; its draft is filed under Synthea patient 1617 |
| The audit log as admin | Waits over 6 s are compressed to 2.5 s, with the real time on screen; after the first 32 s of the consultation, the rest is streamed at 2x and shown compressed |

The UI's demo sign-in is answered by the script with a locally issued token for the synthetic users, so
the API keeps `DEV_LOGIN=false`.

## Scenes

| Scene | Shown |
|---|---|
| Title, architecture | modes; voice → de-ID → LangGraph agent → MCP tools → LiteLLM gateway |
| Voice question | "What is the usual starting dose of warfarin?" → transcript → cited answer (fast path) → spoken answer; time per stage |
| Ask in the review UI | "Does clarithromycin interact with warfarin?" → agentic path, three cited sentences; pointing at a citation lights up its source, a passage opens in place |
| Scribe from audio | PriMock57 day3_consultation02: live diarized transcript (the patient's name, birth date and address are said in the first 30 s) → roles (speaker 0 doctor, speaker 1 patient, 61 turns) → draft (42 statements, 15 without a guideline source, unsure speech marked; name, birth date and address as surrogates) → opened from "Awaiting your review"; pointing at statements lights up their turns → wrong family name **refused**, the draft stays open ("2 attempts left") → corrected → "Approved and saved. FHIR DocumentReference/68511" |
| Audit log (admin) | the run's actions, with model and prompt version |
| Results, end card | measured results, including the voice latency budget not met |

Voice stages in this run (one turn, so no percentiles): end of speech → final transcript 1,113 ms
(endpointing included), Ask 9,049 ms (a slow evening on the free tiers: the agentic Ask in the same take
took 26.9 s), first audio byte 1,539 ms, **time to first audio 11,701 ms** against the 1,500 ms budget.
Over 30 questions the p50 / p95 are 4,296 / 7,093 ms (`evals/reports/voice/latency.md`, 2026-10-19).

## Found while making it

- 2026-10-29: two takes ended without a draft ("no draft produced"). The note writer's calls went to
  `gemini-2.5-flash` in the default pool, which spends the 4,500-token output limit on thinking, and the
  retry came back cut off; the graph then discarded the first attempt, which had been usable. Fixed in
  the graph: when the retry has no valid statements, the first draft is kept without its failing
  statements (PROGRESS, 2026-10-29); the script also asks once more on a 422. The third take drafted
  first time.

- An earlier take used two synthetic TTS voices for the consultation: Deepgram's diarization (live and
  batch) did not tell them apart, so the take uses a real recording.
- An earlier take's draft showed the spoken birth date ("21 12 at 1986") and the spelled-out postcode
  ("N W 36 P Q") unredacted: the de-ID patterns did not know these forms. Fixed (PROGRESS, 2026-10-18)
  before this take.
- Earlier takes drafted the consultation a second time after the refused write; since 2026-10-19 a
  wrong identifier keeps the draft open (up to 3 attempts), and the take shows the correction.
- The refusal shown in this take starts with the tool library's "Error executing tool write_fhir:"
  prefix; since removed (the doctor now sees the server's reason only).

## Not shown

Lab mode (it has a screen since 2026-10-28), failover (`just gate 5`), and the browser Voice tab (the
voice scene runs the same pipeline from the script).

## Re-record

`just up rag`, `npm --prefix apps/web run dev`, then `just demo-video` (about 20 minutes on the free
tiers; `--scenes title,results` records a subset, `--out <folder>` writes elsewhere instead of replacing
this take). Narration audio is cached in `.artifacts/demo/tts/`, so a re-recording
pays only for the live calls: two Ask turns, about 7 minutes of streamed audio, one draft and one spoken
answer.
