# Speech-to-speech: Gemini Live time to first audio (Phase 4)

10 turns (+1 warm-up), synthetic question audio streamed at real-time pace;
model `models/gemini-2.5-flash-native-audio-latest`, server-side voice activity detection.

| metric | p50 ms | p95 ms |
|---|---|---|
| TTFA (last audio frame -> first reply audio) | 3,493 | 6,137 |

Not comparable on quality: these answers are not grounded, cited or guarded (ADR-0011).
