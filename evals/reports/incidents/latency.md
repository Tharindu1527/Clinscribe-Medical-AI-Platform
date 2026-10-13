# Drill: latency spike in a dependency

10 concurrent sessions (3 questions each, mock model), without and with
`CHAOS_SEARCH_DELAY_MS=1500` on guidelines-mcp. The SPEC drill injects the delay into TTS;
voice is not built yet, so the delay goes into guideline search, which every Ask calls.

| run | Ask p50 ms | Ask p95 ms | errors | `mcp search_guidelines` span p50 / p95 ms |
|---|---|---|---|---|
| normal | 2178 | 3768 | 0 | 1981 / 2207 |
| delay 1500 ms | 2504 | 4332 | 0 | 2513 / 4145 |
