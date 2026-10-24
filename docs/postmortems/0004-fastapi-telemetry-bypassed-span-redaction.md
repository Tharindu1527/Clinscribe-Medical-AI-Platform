# Postmortem 0004: FastAPI's own telemetry bypassed the app-level span redaction

Type: real defect, found in passing · Date: 2026-10-24 · Severity: high by design (one of two PHI
defences for traces was off for 19 days), no PHI exposure found

## Summary

FastAPI 0.142 ships OpenTelemetry support that is on by default. When `OTEL_EXPORTER_OTLP_ENDPOINT`
is set, as it is for every service, it installs a global tracer provider with a plain OTLP exporter
before the application's lifespan runs. ClinScribe's `configure_tracing` then tried to install its
own provider, whose exporter redacts span attributes (deny-by-default allow-list); OpenTelemetry
keeps the first global provider, so it was refused with a warning nobody read. In the API and the
de-ID service every span, ClinScribe's and FastAPI's own, left the process unredacted. The second
defence, the collector's redaction processor, removed what the first should have, so no sink ever
held PHI (every leak test: 0 leaks). FastAPI also exported metrics, and would have exported
validation failures with their input values as log records; the collector has no metrics or logs
pipeline, so it rejected both (HTTP 404).

## Timeline

| when | event |
|---|---|
| 2026-10-05 | Phase 1: Compose stack with FastAPI 0.142.2 (lock from the first stack commit); task 7 adds `configure_tracing` + `RedactingSpanExporter` and the collector's redaction processor |
| 2026-10-05 → 10-24 | each API and de-ID start logs "Overriding of current TracerProvider is not allowed" (reproduced on the started API); spans go out through FastAPI's exporter. Unit tests exercise `configure_tracing` alone; integration tests read the collector's output, after its redaction: both pass |
| 2026-10-10 | Langfuse free-tier ingestion suspended (usage threshold); FastAPI's own spans were ~80% of exported spans (sample below), likely a large share of that volume |
| 2026-10-24 | an OTLP *metrics* 404 in the API log (no metrics are configured anywhere) leads to FastAPI's telemetry module; a probe of the started API shows the global provider is FastAPI's, with a plain `OTLPSpanExporter` |
| 2026-10-24 | fix deployed and verified (below) |

## Impact

- No PHI found in traces, logs, Langfuse, spend logs, audit or mapping tables, in any leak-test run
  before or after. The spans ClinScribe creates carry no text by rule (only ids, counts, model
  names), and the collector dropped every attribute outside its allow-list.
- For 19 days the API and de-ID service ran with a single span-redaction layer instead of two.
  The MCP servers (Starlette, not FastAPI) were not affected.
- Trace volume: in the last ~600 kB of the export before the fix, 1,072 of 1,340 spans came from
  FastAPI's own instrumentation (`fastapi` scope), against 134 + 134 from ClinScribe's.

## Root cause

A framework default changed what "configure tracing" meant: the first component to set the global
provider wins, and FastAPI runs its setup before the application's lifespan. Nothing checked which
provider was actually installed in a running service.

## Detection gaps

- Tests checked the redacting exporter in isolation and the end result after the collector, never
  the provider a started service really uses.
- A WARNING at every start-up was not treated as an error.

## Fix

- `llmops/telemetry/setup.py`: `FASTAPI_TELEMETRY` turns FastAPI's tracing, metrics, logs and
  environment auto-configuration off; both FastAPI apps use it. ClinScribe's middleware still makes
  one span per request, now through the redacting exporter.
- `configure_tracing` fails closed: if the global provider is not its own after setting it, the
  service refuses to start instead of exporting unredacted spans.

Verified on the rebuilt stack: the started API's provider has `RedactingSpanExporter` wrapping the
OTLP exporter; no override warnings or metric-export errors in the API or de-ID logs; after the
rebuild no `fastapi`-scope spans reach the collector (the last ones are from the old containers'
final batch, 6 s before the new de-ID container started).

## Prevention

- `tests/unit/test_fastapi_telemetry.py`, each case in a fresh interpreter: FastAPI with the
  project setting installs no provider (and, as a control, FastAPI's defaults do install all
  three); both service apps use the setting; `configure_tracing` refuses to run after another
  provider. A dependency upgrade that changes these defaults fails CI.
- New dependencies get a check of what they do at import or start-up, not only of what we call.
