# De-ID (tagger): recall and over-redaction (synthetic data)

Names/places: `tagger` (tokens: `en_core_web_md`); 200 seeded snippets (Faker seed 42), 11.1 s; per snippet p50 51.8 ms, p95 81.6 ms (in-process).

| Entity | N | Recall | Gate |
|---|---|---|---|
| DATE | 100 | 1.000 | 1.0 |
| AGE_OVER_89 | 20 | 1.000 | 1.0 |
| PHONE | 60 | 1.000 | 1.0 |
| EMAIL | 40 | 1.000 | 1.0 |
| SSN | 20 | 1.000 | 1.0 |
| MRN | 20 | 1.000 | 1.0 |
| HEALTH_PLAN_ID | 20 | 1.000 | 1.0 |
| ACCOUNT_NUMBER | 20 | 1.000 | 1.0 |
| LICENSE_NUMBER | 20 | 1.000 | 1.0 |
| VEHICLE_ID | 20 | 1.000 | 1.0 |
| DEVICE_ID | 20 | 1.000 | 1.0 |
| URL | 20 | 1.000 | 1.0 |
| IP_ADDRESS | 20 | 1.000 | 1.0 |
| STREET_ADDRESS | 40 | 1.000 | 1.0 |
| ZIP | 40 | 1.000 | 1.0 |
| PERSON | 120 | 1.000 | 0.99 |
| LOCATION | 60 | 1.000 | 0.98 |

Over-redaction: **0 of 80** PHI-free clinical sentences altered (0.0%; gate 1%).

Misses by template (entity@template: count): none

## Held out (no gate): new phrasings and seed, not used to design the recognisers

| Entity | N | Recall |
|---|---|---|
| PERSON | 110 | 0.991 |
| LOCATION | 60 | 1.000 |
| DATE | 10 | 1.000 |
| PHONE | 20 | 1.000 |
| EMAIL | 10 | 1.000 |
| STREET_ADDRESS | 10 | 1.000 |
| ZIP | 10 | 1.000 |

Held-out misses (entity@template: count): {'PERSON@h9': 1}

Gate: **PASS**

Limits: template-based synthetic text; Faker draws names from US Census-style lists, so
recall is optimistic. Real dictation (Phase 2 transcripts) is the harder test.
