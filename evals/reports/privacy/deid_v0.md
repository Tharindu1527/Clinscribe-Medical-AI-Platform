# De-ID v0 recall (synthetic corpus)

Model `en_core_web_md`, 200 seeded snippets (Faker seed 42), 3.5 s total; per snippet p50 16.7 ms, p95 22.2 ms (in-process).

| Entity | Kind | N | Recall |
|---|---|---|---|
| DATE | structured (gate 1.0) | 100 | 1.000 |
| AGE_OVER_89 | structured (gate 1.0) | 20 | 1.000 |
| PHONE | structured (gate 1.0) | 60 | 1.000 |
| EMAIL | structured (gate 1.0) | 40 | 1.000 |
| SSN | structured (gate 1.0) | 20 | 1.000 |
| MRN | structured (gate 1.0) | 20 | 1.000 |
| HEALTH_PLAN_ID | structured (gate 1.0) | 20 | 1.000 |
| ACCOUNT_NUMBER | structured (gate 1.0) | 20 | 1.000 |
| LICENSE_NUMBER | structured (gate 1.0) | 20 | 1.000 |
| VEHICLE_ID | structured (gate 1.0) | 20 | 1.000 |
| DEVICE_ID | structured (gate 1.0) | 20 | 1.000 |
| URL | structured (gate 1.0) | 20 | 1.000 |
| IP_ADDRESS | structured (gate 1.0) | 20 | 1.000 |
| STREET_ADDRESS | structured (gate 1.0) | 40 | 1.000 |
| ZIP | structured (gate 1.0) | 40 | 1.000 |
| PERSON | NER (baseline) | 120 | 0.950 |
| LOCATION | NER (baseline) | 60 | 0.750 |

Gate (structured recall = 1.0): **PASS**

Missed types (no PHI values are written to this report):
- LOCATION: first miss in template 1
- PERSON: first miss in template 1

Limits: template-based synthetic text, not real dictation; names and places depend on
spaCy NER and are the baseline for the Phase 5 LoRA fine-tuned model.
