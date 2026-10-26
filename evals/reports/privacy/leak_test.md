# PHI leak test (Phase 1 gate b)

Run `0a9456bc`: 20 synthetic transcripts, 66 seeded fake PHI values (Faker seed 1234), sent through `POST /v1/dev/complete`.

| Sink | Bytes scanned | Leaked values | Leaked types |
|---|---|---|---|
| collector file export | 85,555 | 0 | - |
| docker compose logs | 125,883 | 0 | - |
| Langfuse observations | 439 | 0 | - |
| LiteLLM spend logs | 203,179 | 0 | - |
| audit table | 13,774 | 0 | - |
| de-ID mapping table | 13,864 | 0 | - |
| Prometheus label values | 1,477 | 0 | - |
| Phoenix spans | 69,230 | 0 | - |

Positive control (scanner finds planted seed values): **100%**

Gate b (0 leaks in traces and logs, control 100%, every sink non-empty): **PASS**

## Not part of gate b: what the LLM saw

Seed values that survived de-ID in the text sent to the gateway: **0 of 66** (none).
Structured identifiers are covered by regex recognisers; names and places depend on
the name/place recogniser (`DEID_NER=tagger` in `.env`; ADR-0004, ADR-0014).
