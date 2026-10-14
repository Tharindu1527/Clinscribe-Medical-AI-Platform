# Cascaded voice latency per stage (Phase 4)

30 of 30 turns answered (golden questions, seed 4); production
providers: Deepgram nova-3 streaming (endpointing 300 ms), the ClinScribe Ask graph
(Groq gpt-oss-20b answer, CPU retrieval), Cartesia sonic-2 streaming TTS. Budget (SPEC §1):
TTFA p95 < 1,500 ms, turn time p95 < 2,500 ms.

| stage | p50 ms | p95 ms |
|---|---|---|
| STT final (last audio frame -> final transcript, incl. endpointing) | 704 | 1,747 |
| Ask: de-ID + graph + retrieval + cited answer + guardrails | 1,864 | 18,493 |
| TTS first byte (first answer sentence) | 812 | 1,301 |
| **TTFA** (sum per turn) | 3,545 | 19,732 |
| Turn time (TTFA + spoken answer) | 17,287 | 32,342 |

Transcripts identical to the question text (after normalisation): 18/30; agentic route: 6/30.
Early end of utterance (Deepgram endpointing at 300 ms fired at a pause inside the
question: a VAD-style turn end would cut the doctor off here): 1/30 questions.
Turn time estimates the spoken answer at ~150 words per minute after the first sentence.

## By route

| route | turns | Ask p50 / p95 ms | TTFA p50 / p95 ms |
|---|---|---|---|
| fast | 24 | 1,864 / 4,119 | 3,276 / 5,577 |
| agentic | 6 | 3,021 / 22,399 | 4,387 / 24,405 |

## Bottleneck (budget TTFA p95 < 1,500 ms: not met)

Even with every stage at its median (0.7 + 1.9 + 0.8 s), TTFA is 3.5 s. In order of size:
1. **Ask** waits for the whole cited answer (non-streaming JSON, gpt-oss reasoning first) and,
   on the agentic path, for grading and a query rewrite: p95 18.5 s. Fix: stream the first cited
   sentence, keep voice on the fast path (route agentic questions to the screen), lower the
   reasoning effort for Ask.
2. **STT final** includes the 300 ms endpointing wait; a semantic end-of-turn model can end turns
   earlier when the words are complete (the voice agent supports it; not measured here).
3. **TTS first byte** ~0.8 s over the internet from this laptop; a nearer region or a WebSocket
   session reused across turns removes connection set-up.
Measured stage by stage from the client; the per-tool spans (`mcp search_guidelines`) and gateway
spans locate the time inside Ask (postmortem 0003 shows the method).
