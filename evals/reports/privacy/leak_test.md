# PHI leak test (Phase 1 gate b)

Run `f3d5918c`: 20 synthetic transcripts, 66 seeded fake PHI values (Faker seed 1234), sent through `POST /v1/dev/complete`.

| Sink | Bytes scanned | Leaked values | Leaked types |
|---|---|---|---|
| collector file export | 436,091 | 0 | - |
| docker compose logs | 918,027 | 0 | - |
| Langfuse observations | 249,069 | 0 | - |
| LiteLLM spend logs | 199,999 | 0 | - |
| audit table | 14,180 | 0 | - |
| de-ID mapping table | 13,641 | 0 | - |

Positive control (scanner finds planted seed values): **100%**

Gate b (0 leaks in traces and logs, control 100%, every sink non-empty): **PASS**

## Not part of gate b: what the LLM saw

Seed values that survived de-ID in the text sent to the gateway: **2 of 66** (LOCATION 2).
Structured identifiers are covered by regex recognisers; names and places depend on
spaCy NER.
