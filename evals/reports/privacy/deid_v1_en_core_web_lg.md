# De-ID v1: recall and over-redaction (synthetic data)

Model `en_core_web_lg`; 200 seeded snippets (Faker seed 42), 3.1 s; per snippet p50 14.9 ms, p95 19.3 ms (in-process).

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

Over-redaction: **1 of 80** PHI-free clinical sentences altered (1.2%; gate 1%).
- #7 (LOCATION): LOCATION_1 Coma Scale 15 on arrival.

Misses by template (entity@template: count): none

## Held out (no gate): new phrasings and seed, not used to design the recognisers

| Entity | N | Recall |
|---|---|---|
| PERSON | 110 | 1.000 |
| LOCATION | 60 | 0.650 |
| DATE | 10 | 1.000 |
| PHONE | 20 | 1.000 |
| EMAIL | 10 | 1.000 |
| STREET_ADDRESS | 10 | 1.000 |
| ZIP | 10 | 1.000 |

Held-out misses (entity@template: count): {'LOCATION@h3': 6, 'LOCATION@h5': 7, 'LOCATION@h7': 4, 'LOCATION@h8': 4}

Gate: **FAIL: over-redaction 1.2% > 1%**

Limits: template-based synthetic text; Faker draws names from US Census-style lists, so
recall is optimistic. Real dictation (Phase 2 transcripts) is the harder test.
