# Postmortem 0003: latency spike in a dependency, located from traces

Type: injected incident (drill, `evals/incidents/drills.py latency`) · Date: 2026-10-14 ·
Severity: low (slower answers, no failures)

## Summary

`CHAOS_SEARCH_DELAY_MS=1500` added 1.5 s to every guideline search while 10 sessions used the Ask
endpoint (mock model, as in the load test). The SPEC drill puts the delay in text-to-speech; voice is
not built yet, so the delay went into the one dependency every Ask calls. Answers kept succeeding;
the p95 rose and the trace showed which step caused it.

## Measurements (10 concurrent sessions, 3 questions each)

| run | Ask p50 ms | Ask p95 ms | errors | `mcp search_guidelines` span p50 / p95 ms |
|---|---|---|---|---|
| normal | 2,178 | 3,768 | 0 | 1,981 / 2,207 |
| +1,500 ms in search | 2,504 | 4,332 | 0 | 2,513 / 4,145 |

## Detection

- Symptom: Ask p95 up 15% (3.8 → 4.3 s); against a voice budget (TTFA p95 < 1.5 s) this would be an
  alert, for typed Ask it is not.
- Location: the per-tool spans added to the agent's MCP client (`mcp <tool>` in
  `agents/tools.py`) show the `mcp search_guidelines` p95 nearly doubling (2.2 → 4.1 s) while the
  gateway spans stay flat; `just logs guidelines-mcp` and the service's settings then show the delay.

## Why the effect is smaller than the injected delay

Under load, searches already queue for the CPU (encoders, BM25 and ColBERT in one process; see
`evals/reports/load/load_test.md`). A sleeping request frees the CPU for the others, so part of the
1.5 s overlaps with waiting that happened anyway; the p50 rises by ~0.5 s, the tail by ~1.9 s.

## Fix and prevention

- Restore: unset `CHAOS_SEARCH_DELAY_MS`, recreate guidelines-mcp (the drill does this in `finally`).
- Per-tool spans are now part of every request, so a slow tool is visible without extra logging.
- Gap: no alert rule is deployed (Grafana/Prometheus are in the optional `obs` profile, not set up);
  the drill was detected by reading spans, not by an alert.
