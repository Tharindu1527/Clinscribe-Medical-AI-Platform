# ADR-0023: Dashboards from span metrics and the gateway's spend log

Status: Proposed · Date: 2026-10-26

## Context

SPEC §7 asks for Grafana dashboards with p50/p95 latency per stage, error rate, failover count and
cost per consultation. Traces went to a local file and to Langfuse Cloud; nothing produced
metrics. Looking at what the dashboards would be built on showed five problems:

- Container health checks were most of the spans (3,531 of the last ~3,600 in the trace file) and
  were exported to Langfuse too, on a free tier that had already run out once.
- API spans were named by the raw path (`POST /v1/lab/lab-fc9a.../confirm`), one name per request.
- The collector's redaction processor also redacts resource attributes, and `service.name` was not
  on the allow-list: no span, in the file or in Langfuse, said which service sent it.
- The trace file had grown to 45 MB since 2026-10-05 with no rotation.
- Nothing marks a failover. "Served by a fallback alias" is not one: answers ask for
  `clinscribe-fallback-groq` by design (`config/models.yaml`), and the spend log does not record
  which alias the app asked for.

## Options

1. **Langfuse dashboards**: traces only (no cost per consultation), cloud, and its ingestion was
   suspended by the free tier.
2. **LiteLLM's own metrics**: only the gateway stage; nothing for the API, de-ID or retrieval.
3. **Grafana Cloud's free tier**: another processor receiving the telemetry.
4. **Local Prometheus and Grafana** (Compose profile `obs`): per-stage metrics made by the
   collector from the spans it already redacts (the `spanmetrics` connector), plus the spend log
   read directly, after tagging each gateway call with the alias asked for and its encounter.

## Decision

Option 4.

- Spans: API spans named by route template (`POST /v1/drafts/{draft_id}/review`; the path stays in
  `url.path`), 5xx responses marked as errors, `/health` not traced, `service.name` allow-listed in
  both redaction layers.
- Metrics: the collector's `spanmetrics` connector on the redacted trace pipeline (calls, errors,
  a latency histogram from 25 ms to 300 s per service and span name; extra labels only the
  allow-listed status code and requested model), exported to Prometheus (15 days kept).
- Spend log: the gateway client sends `metadata.spend_logs_metadata` with `requested_alias` and,
  inside `for_encounter(...)`, `encounter_id`; the API sets the encounter around every graph run,
  outside the replay-cache key. A failover is a successful call served by another alias than the
  one asked for. Grafana reads the spend log through `grafana_reader`, which has SELECT on ten
  columns of that one table (no request or response content, no keys).
- Grafana `12.4.12` (pinned, a maintained line), local only (127.0.0.1), no sign-up, no anonymous
  access, no usage reporting or update checks; one provisioned dashboard, "ClinScribe operations",
  that the UI cannot change. Grafana 13.2.3 was tried first: it loads the Prometheus and
  PostgreSQL plugins after start, so on early loads panels failed ("Plugin not registered", data
  source "not found"), and it used 471 MiB against 12.4.12's 137 MiB after the same use (image
  1.94 vs 1.18 GB). 12.4.12 bundles both plugins and registers them at start.
- The trace file rotates at 100 MB (3 backups, 30 days); the PHI leak test scans the backups too.

## Consequences

- Measured on the running stack with one synthetic consultation (a Scribe draft and three Ask
  questions) and one draft with the primary provider down: all 18 panel queries run through
  Grafana's query API without an error; the failover was counted (asked for
  `clinscribe-default`, served by `clinscribe-fallback-groq`); cost per encounter at list price:
  Ask questions about $0.0002, the Gemini-served draft $0.0046 and the failover draft $0.0003.
  The PHI leak test now also scans every Prometheus label value: gate b PASS, 0 leaks in all
  sinks, 0 of 66 seed values reached the model.
- p50/p95 come from histogram buckets, so they are estimates within a bucket (a 117 s draft shows
  as 114 s, inside the 60–120 s bucket).
- The per-stage table reads the collector's cumulative counters ("since the collector started").
  `increase()` over the dashboard range cannot count a series' first observations; on a quiet
  stack it dropped the 117 s draft from p95 entirely in the first check.
- The integration test checks that both data-source plugins are registered, so a Grafana
  upgrade that drops one from the image fails it.
- Cost is LiteLLM's list price; the free tiers bill $0. Only calls made after this change carry
  the tags; evaluation and batch jobs send `no-log`, so they leave no spend-log row at all.
- Memory: Prometheus 62 MiB, Grafana 137 MiB after use; the stack with core, fhir, rag, voice and
  obs measured 6.08 GB (within the 8 GB budget, ADR-0003).
- Not done: alerts (SPEC §7's incident drills read traces directly), Arize Phoenix comparison (a
  separate SPEC item).
