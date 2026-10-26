# Lab mode: HL7 v2 ORU^R01 -> FHIR Observations (ADR-0021)

20 Synthea patients' latest lab panels written as ORU^R01 (v2.5.1) messages with
the record's MRN, name and birth date, then read back with `agents/lab/hl7.py` (no
model).
Reference intervals: `config/lab_reference.yaml` (illustrative adult values).

| check | correct | of |
|---|---|---|
| result mapped to the right LOINC code | 155 | 155 |
| value exact | 155 | 155 |
| unit as expected (UCUM) | 155 | 155 |
| H/L/N flag | 155 | 155 (16 abnormal) |
| preliminary FHIR Observation built | 155 | 155 |
| collection date | 20 | 20 |
| identity matches its record (name, birth date, MRN) | 20 | 20 |
| wrong-patient control caught | 20 | 20 |
| ... of which by the MRN alone | 20 | 20 |
| same result with newline endings and MLLP framing | 20 | 20 |
| results listed as not readable | 0 | — |

Limits: one synthetic sender, written by the same project as the reader, so this shows
the mapping and the checks, not robustness to real senders (local codes instead of LOINC,
structured numerics such as `>60`, Z-segments, v2.3 vs 2.5.1 differences, batches).
Unit tests cover escape sequences, other separators, non-numeric and non-final results.

| patient | tests | collected | flagged H/L |
|---|---|---|---|
| 1617 | 2 | 2026-10-01 | 1 |
| 2631 | 9 | 2026-01-26 | 1 |
| 3346 | 8 | 2024-03-21 | 2 |
| 3599 | 8 | 2023-10-10 | 0 |
| 3950 | 21 | 2026-06-07 | 3 |
| 4675 | 9 | 2024-10-13 | 2 |
| 5267 | 8 | 2024-07-18 | 0 |
| 5608 | 8 | 2022-04-27 | 1 |
| 5898 | 2 | 2017-08-26 | 1 |
| 21637 | 8 | 2024-10-29 | 0 |
| 22012 | 8 | 2026-02-16 | 0 |
| 22575 | 8 | 2026-08-11 | 1 |
| 23005 | 4 | 2026-04-30 | 2 |
| 23396 | 8 | 2023-07-03 | 0 |
| 24194 | 8 | 2026-06-21 | 2 |
| 24395 | 8 | 2025-11-24 | 0 |
| 24922 | 8 | 2023-05-17 | 0 |
| 25318 | 8 | 2025-08-11 | 0 |
| 25445 | 8 | 2025-08-15 | 0 |
| 25777 | 4 | 2023-12-09 | 0 |
