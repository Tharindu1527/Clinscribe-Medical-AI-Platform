# Postmortem 0001: primary provider outage — answers failed on a single-provider alias

Type: injected incident (drill, `evals/incidents/drills.py outage`) · Date: 2026-10-14 ·
Severity: high (half of the clinicians' questions failed during the outage)

## Summary

With the primary model (Gemini) unreachable, 2 of 4 Ask questions returned HTTP 502 although the
gateway's failover worked. Answer generation is bound to the Groq alias (`answer_cited`, chosen in
Phase 2 so every evaluated pipeline used the same generator), and that alias had no fallback chain:
when the outage moved all traffic onto Groq, a single Groq failure failed the whole request.

## Timeline (UTC, 2026-10-13)

| time | event |
|---|---|
| 19:44 | `just chaos primary-down on` (Gemini pointed at a dead address); 4 agentic questions sent |
| 19:44:48 | Groq call fails (spend log status `failure`); question 2 returns 502 after 23.2 s |
| 19:45:12 | second Groq failure; question 3 returns 502 after 16.5 s |
| 19:46 | questions 1 and 4 answered (4.9 s, 51.0 s); chaos off |
| 19:50 | fix: fallback chain for the Groq alias; API logs gateway failure status and type |
| 19:52 | drill repeated: 4/4 answered (5.1–44.3 s); spend log Groq 8, local Ollama 2 |

## Detection

- Users: HTTP 502 "the model gateway failed" from `/v1/ask`.
- Gateway spend log (`LiteLLM_SpendLogs`): every call in the window served by
  `groq/openai/gpt-oss-20b` (failover active), two with status `failure`, no fallback after them.
- Not available: the provider's error text. The gateway stored no error row and the API swallowed
  the exception into a 502 without logging it, so the exact Groq error (rate limit or its JSON-mode
  validator, seen before in Phase 3) could not be recovered.

## Root cause

`config/models.yaml` maps `answer_cited` to `clinscribe-fallback-groq`; `router_settings.fallbacks`
only defined a chain for `clinscribe-default`. A task bound to a fallback alias inherits none of the
chain, so the system was only as available as Groq.

## Fix

- `llmops/gateway/config.yaml`: `clinscribe-fallback-groq` falls back to OpenRouter, then local Ollama.
- `apps/api/clinical.py`: gateway failures are logged with exception type and HTTP status (not the
  message text, which can echo de-identified prompt content).

## Prevention

- Every alias a task can be mapped to gets a fallback chain; a unit test should assert this (gap).
- The outage drill runs through the API with agentic questions, not just one gateway call (the
  Phase 1 failover test called `clinscribe-default` directly and could not see this).
- Latency during fallback to the local model is 23–44 s per question: acceptable for an outage, not
  for voice; the voice phase needs a faster last resort or a degraded "text only" mode.
