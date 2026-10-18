# Cascaded voice latency per stage (Phase 4)

29 of 30 turns answered (golden questions, seed 4); production
providers: Deepgram nova-3-medical streaming (endpointing 300 ms), the ClinScribe Ask
graph (Groq gpt-oss-20b answer, CPU retrieval), Deepgram Aura-2 streaming TTS
(aura-2-orpheus-en; ADR-0013). Measured 2026-10-19.
Budget (SPEC §1):TTFA p95 < 1,500 ms, turn time p95 < 2,500 ms.

| stage | p50 ms | p95 ms |
|---|---|---|
| STT final (last audio frame -> final transcript, incl. endpointing) | 730 | 1,910 |
| Ask: de-ID + graph + retrieval + cited answer + guardrails | 2,113 | 4,856 |
| TTS first byte (first answer sentence) | 1,413 | 1,550 |
| **TTFA** (sum per turn) | 4,296 | 7,093 |
| Turn time (TTFA + spoken answer) | 15,508 | 31,336 |

Transcripts identical to the question text (after normalisation): 19/30; agentic route: 5/29.
Early end of utterance (Deepgram endpointing at 300 ms fired at a pause inside the
question: a VAD-style turn end would cut the doctor off here): 1/30 questions.
Turn time estimates the spoken answer at ~150 words per minute after the first sentence.
