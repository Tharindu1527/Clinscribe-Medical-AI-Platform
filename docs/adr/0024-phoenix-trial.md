# ADR-0024: Arize Phoenix tried against Langfuse Cloud on the same spans

Status: Proposed · Date: 2026-10-27

## Context

SPEC §7: "Arize Phoenix is tried once and compared in an ADR." ADR-0002 chose Langfuse Cloud's free
tier because self-hosted Langfuse v3 needs ClickHouse, Redis and object storage, several GB of a
machine whose stack must stay under 8 GB. Since then Langfuse Cloud has suspended this
organisation's ingestion ("usage threshold exceeded", since 2026-10-10): the collector still
sends, Langfuse refuses, and only the local file export holds traces. Langfuse is also a
subprocessor in the DPIA. Phoenix is one container with SQLite and accepts OTLP.

## Options

1. **Keep Langfuse Cloud only** and wait for the monthly reset (or a paid plan).
2. **Replace Langfuse with self-hosted Phoenix.**
3. **Keep Langfuse Cloud as configured and add Phoenix as an optional local backend**, fed the
   same redacted spans, for when traces must not leave the machine or the cloud quota is gone.

## Decision

Option 3, after one measured trial (`just phoenix on`, `evals/llmops/tracing_compare.py`,
`evals/reports/llmops/tracing_backends.md`).

- `docker-compose.phoenix.yml` adds Phoenix `20.21.1` (127.0.0.1:6006, usage telemetry off, data in
  a volume) and merges `llmops/telemetry/collector.phoenix.yaml` into the collector, which then
  exports the same redacted spans to the file, Langfuse and Phoenix. `just phoenix off` stops it and
  restores the collector. Nothing changes for the default stack.
- Langfuse stays the configured backend: SPEC names it, the Phase 1 tests read traces back from
  it, and it is free while the quota lasts. Prompts and scores do not depend on either tool (they
  live in `prompts/*.yaml` and `evals/reports/`). Replacing Langfuse is not decided on one trial;
  the trial shows Phoenix could take over, with its authentication switched on.

## Consequences

- Same traffic, same spans (one synthetic consultation: a draft, its rejection and three Ask
  questions, real models, run twice): Phoenix stored 71 of 71 and 70 of 70 spans of the 5 traces
  that the file export holds, trace trees intact (API → de-ID → MCP tools → model call → LiteLLM's
  request span). Langfuse stored 0 both times: ingestion is still suspended.
- Phoenix needs no instrumentation change. It reads the OpenTelemetry GenAI attributes our spans
  carry and fills its own model and token fields from them (`gen_ai.request.model` →
  `llm.model_name`, `gen_ai.usage.*_tokens` → `llm.token_count.*`), marking the model-call spans as
  LLM spans (9 of 71, 8 of 70; the rest are "unknown", which is right for HTTP and tool spans).
- Its cost column shows $0: it prices from its own model table, which does not know LiteLLM's
  aliases or the Groq deployment names. Cost stays with the gateway's spend log (ADR-0023).
- Resources: image 1.42 GB; 448–599 MiB of memory (the limit is 768 MB); about 2 MiB of data after
  the trial. First start ~60 s to a working UI (database migrations), a restart 29 s.
  Lighter than self-hosted Langfuse v3, heavier than "one small container" suggests; with every
  profile up it would take the stack to ~6.7 GB, inside the 8 GB budget.
- PHI: Phoenix receives only what the collector exports after both redaction layers, the same
  spans as the file export. The PHI leak test scans Phoenix as a sink whenever the trial runs; with
  the trial on: gate b PASS, 0 leaks in all 8 sinks (69,230 bytes of Phoenix spans), 0 of 66 seed
  values reached the model.
- No access control by default (anyone who can reach 127.0.0.1:6006 reads the traces). Phoenix's
  authentication would have to be switched on before any shared use. Its UI also shows an "update
  available" banner, so it checks for releases even with usage telemetry off.
- Not compared on this trial: prompt management, evaluation runs and datasets in either tool (the
  project keeps prompts in `prompts/*.yaml` and evaluation results in `evals/reports/`).
