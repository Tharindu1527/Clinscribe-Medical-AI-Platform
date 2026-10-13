# Postmortem 0002: retrieval drift after an index rebuilt with the wrong chunking config

Type: injected incident (drill) · Date: 2026-10-14 · Severity: medium (answer quality, no data risk)

## Summary

The chosen pipeline's dense and ColBERT indexes were swapped for an index built with the rejected
late-chunking configuration (`late_chunking` in `config/retrieval.yaml`, ADR-0005 note), as would happen
if a re-index ran with the wrong variant. Answers kept their citations, so nothing looked broken to a
user; only the evaluation showed the drop.

## Injection

Replayed from the stored run of the same configuration (`evals/reports/rag/runs/hybrid_colbert_late.json`,
re-timed 2026-10-13, rankings identical to its first run) against the chosen pipeline
(`hybrid_colbert_ctx`). A live swap would only change which collection guidelines-mcp reads; the
measured effect is the same rankings.

## Detection

`just eval rag` with `--compare hybrid_colbert_ctx hybrid_colbert_late` (209 golden questions, paired
bootstrap 95% CI):

| metric | expected | after the bad rebuild | difference [95% CI] |
|---|---|---|---|
| recall@1 | 0.565 | 0.464 | −0.100 [−0.163, −0.038] |
| recall@10 | 0.909 | 0.861 | −0.048 [−0.091, −0.005] |
| MRR@10 | 0.680 | 0.599 | −0.081 [−0.127, −0.036] |
| nDCG@10 | 0.695 | 0.627 | −0.068 [−0.106, −0.028] |

Every interval excludes 0: a regression, not noise. The CI fixture (`tests/fixtures/rag_mini`) would
**not** have caught it: it checks the first-stage code (BM25, RRF, metrics) on committed vectors, not a
rebuilt production index.

## Root cause

Late chunking pools token vectors per chunk from a whole-section encoding; with ModernBERT Embed the
chunk vectors of long sections converge (mean within-section cosine 0.923 vs 0.706), so chunks of the
same section become hard to tell apart (PROGRESS, Phase 2 task 8).

## Fix and prevention

- Roll back: re-point to the contextual collection (`docs/runbooks/operations.md`, "Re-index").
- Index names carry the variant and a fingerprint of the corpus and config (`chunks_dense_modernbert_ctx_v1`,
  `meta.json`), so the serving variant is visible; the re-index runbook now ends with `just eval rag` and a
  comparison against `evals/reports/rag/ablation.md` before switching.
- Gap: the nightly evaluation that would alert on this automatically (SPEC §7) is designed, not deployed.
