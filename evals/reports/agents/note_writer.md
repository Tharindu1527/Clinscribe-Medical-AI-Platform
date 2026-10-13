# Note writer on ACI-Bench (Phase 3 task 6)

8 validation dialogues (seed 3, CC BY 4.0), de-identified turn by turn, then the scribe
path of the graph with the real model up to the doctor-review interrupt (prompt
`note_writer@v2`, alias `clinscribe-default`).

- drafts produced: 6/8
- schema-valid and guardrail-clean on the first attempt: 5/8 (62%); the rest needed the one retry
- statements: 148 (24.7 per draft); by section: subjective 62, objective 40, plan 31, assessment 15
- assessment/plan statements without a guideline citation (highlighted for the doctor): 46
- problems after the retry (statements removed): unsourced_dose 3, Expecting ',' delimiter 2, the note has no valid statements 2
- latency per draft (uncached runs): p50 67 s, p95 179 s

| dialogue | turns | draft | attempts | statements | unsupported | removed |
|---|---|---|---|---|---|---|
| aci-D2N075 | 59 | no | 2 | 0 | 0 | 2 |
| aci-D2N086 | 21 | yes | 1 | 25 | 7 | 0 |
| aci-D2N085 | 7 | yes | 1 | 33 | 14 | 0 |
| aci-D2N072 | 49 | yes | 1 | 22 | 3 | 0 |
| aci-D2N079 | 40 | yes | 1 | 23 | 8 | 0 |
| aci-D2N082 | 53 | yes | 1 | 23 | 8 | 0 |
| aci-D2N077 | 81 | no | 2 | 0 | 0 | 2 |
| aci-D2N087 | 83 | yes | 2 | 22 | 6 | 3 |

Findings: the two long consultations (59 and 81 turns) failed both attempts with truncated JSON
(`Expecting ',' delimiter`): input plus the model's reasoning plus ~25 statements do not fit the 4,500
output tokens that Groq's free-tier per-minute token limit leaves room for. Fix options: write long
consultations in segments, or route long transcripts to a model with a larger output budget. Groq's
JSON mode rejected valid long notes (`json_validate_failed`), so the graph parses JSON itself.

