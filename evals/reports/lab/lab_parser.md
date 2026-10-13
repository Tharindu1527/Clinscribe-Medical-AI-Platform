# Lab mode: report PDF -> FHIR Observations (Phase 5)

20 Synthea patients' latest lab panels rendered as text PDFs (one fixed
layout) and parsed back with `agents/lab/parser.py` (pypdf text, no model). Reference
intervals: `config/lab_reference.yaml` (illustrative adult values).

| field | correct | of |
|---|---|---|
| test row found | 155 | 155 |
| mapped to the right LOINC code | 155 | 155 |
| value exact | 155 | 155 |
| unit as expected | 155 | 155 |
| H/L/N flag | 155 | 155 (16 abnormal) |
| report identity matches its patient | 20 | 20 |
| wrong-patient control caught | 20 | 20 |
| unreadable rows | 0 | — |

Limits: one synthetic layout; no scanned images, handwriting, multi-column or
vendor-specific layouts. A real deployment needs OCR (Docling or Tesseract) and a layout
test set per lab.

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
