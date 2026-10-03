# ADR-0002: Langfuse Cloud instead of self-hosted Langfuse

Status: Accepted · Date: 2026-10-04

## Context

The spec uses Langfuse for traces, prompt versions and evaluation scores. The dev machine has 16 GB RAM
with WSL2 capped at 10 GB, and the core Docker stack must stay under about 8 GB (ADR-0003).
Self-hosted Langfuse v3 needs its web and worker containers plus Postgres, ClickHouse, Redis and S3-compatible
storage (MinIO). That is several GB on its own, before HAPI FHIR, Qdrant, Neo4j or the voice stack.

## Options

1. **Self-hosted Langfuse v3** in Docker. Data stays local, but it would take a large share of the memory budget.
2. **Langfuse Cloud, free tier, EU region.** No local memory cost. Traces leave the machine, and
   free-tier limits apply to monthly volume and retention (check the current limits at sign-up).
3. **Arize Phoenix, self-hosted** (one container). Light, but the spec names Langfuse as the main
   tool; Phoenix is already planned as a one-off comparison.
4. **No hosted tracing:** OTel collector to local files or Jaeger only. Cheapest, but it loses prompt
   versioning, scores and the trace UI that the operator stories depend on.

## Decision

Option 2: Langfuse Cloud free tier in the EU region (`https://cloud.langfuse.com`). This is acceptable because:

- all data in this project is synthetic (SPEC section 9);
- traces are de-identified before export (`privacy/deid`), and the OTel collector applies a second
  redaction pass;
- the PHI leak test (Phase 1, task 10) pulls the run's traces back from Langfuse and scans them.

## Consequences

- Langfuse is a subprocessor. It is listed in the subprocessor list and the DPIA. A real deployment would
  need a DPA with Langfuse or a switch to self-hosting. Both are documented, not built.
- Free-tier volume limits mean load tests sample traces rather than export every span.
- The collector also writes a local file export, so tracing evidence and the leak test still work offline.
- Switching back to self-hosted only changes the collector's exporter endpoint and credentials.
