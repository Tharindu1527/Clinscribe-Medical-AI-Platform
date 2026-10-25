# ADR-0017: Runtime citation support check — a local NLI check is not adopted

Status: Proposed · Date: 2026-10-25

## Context

SPEC §6 (citation grounding): "A separate check confirms that each cited chunk actually supports
its sentence. Unsupported sentences are removed or flagged." SPEC §1 sets citation precision
≥ 0.95. At runtime ClinScribe checks that every citation exists and that every dose is in a cited
source (guardrails), but not that a cited chunk supports its sentence. Phase 2 measured citation
precision (the judge's share of links rated "supports") at 0.875 for the chosen pipeline and 0.926
for dense-only, per-answer means; most failures are "partial" links on sentences that cite two
sources, i.e. over-attribution rather than unsupported claims.

The Phase 2 judgments give labelled data for free: 362 (sentence, cited chunk) links from three
pipelines, rated 307 "supports", 47 "partial", 8 "no".

## Options

1. **A local NLI cross-encoder** in-process on public guideline text and de-identified answers
   (allowed by ADR-0001), dropping or pruning citations it does not find entailed.
2. **An LLM verifier through the gateway**: one more call per answer (~2.5k tokens, 1–3 s), from a
   model family other than the evaluation judge, or the measurement becomes circular.
3. **No runtime check**; report the gap and keep the evaluation-time judge.

Option 1 was measured (`evals/rag/citation_support.py`, `evals/reports/rag/citation_support.md`;
no LLM calls): three Apache-2.0 models (`nli-deberta-v3-xsmall`, `-small`, `nli-MiniLM2-L6-H768`),
each on the whole chunk and on its best 2-sentence window (SummaC style), with two policies and a
threshold chosen by 2-fold cross-validation over questions. On the chosen pipeline (140 links;
precision pooled over links is 0.814, the per-answer mean 0.875):

| | Precision (links, before 0.814) | Supported links kept | Answers emptied | CPU per answer p50 |
|---|---|---|---|---|
| Best ranking (AUC) | AUC 0.58–0.75 for all six variants | | | |
| Drop below threshold, sentence dropped if uncited | 0.89–0.97 | 25–45% | 19–29 of 49 | 0.4–1.7 s |
| Keep each sentence's best citation, prune the rest | 0.83–0.86 | 75–84% | 0 of 49 | 0.4–1.7 s |

## Decision

Option 3 for now. A local NLI check does not reach the target without deleting most good
citations (threshold policy: up to 29 of 49 answers emptied), and its safe variant gains 0.02–0.05
precision while removing 16–25% of the supported citations and adding up to 1.7 s per answer.
Both fail the project's rule that an added technique must beat the baseline in the evaluation.

## Consequences

- Citation precision stays below the SPEC §1 target (0.875 vs 0.95) and is reported as not met in
  the README. The runtime check described in SPEC §6 is not built.
- The likeliest route to the target is the generator itself: fewer multi-source citations (a prompt
  rule such as "cite the one passage that states it"), measured with the existing answer
  evaluation. That needs about 60 generations and 60 judgments on the free tiers (~1 day of Groq
  budget), and a regression check on correctness and abstention.
- Generator trial (2026-10-25, `prompts/experiments/answer_cited_v2.yaml`: "cite the source that
  states it; if a claim needs two sources, write two sentences"), on the chosen pipeline's 60
  questions (`--name hybrid_colbert_ctx_v2`). Adoption rule, written before the run finished: adopt
  v2 only if citation precision is better (95% CI excludes 0), correctness is non-inferior (lower CI
  bound ≥ −0.05, the Phase 2 gate's margin) and correct abstentions on unanswerable questions do not
  drop. Result, 60 of 60 (`evals/reports/rag/answers_hybrid_colbert_ctx_v2_vs_hybrid_colbert_ctx.md`):
  citation precision 0.865 → **0.963** (+0.098 [+0.041, +0.158]: better, above the target), but
  correctness 0.910 → 0.870 (−0.040 [−0.110, +0.020]: non-inferiority not shown), false abstentions
  2% → 6%, and correct abstentions 10/10 → 9/10. **Not adopted** (two of three criteria fail).
  The one unanswerable question v2 answered asked about mazdutide, which the corpus does not cover;
  v2 answered with three sentences from the Ozempic (semaglutide) label, each faithful to its
  source, without naming either drug: a wrong-drug answer that no current check catches.
- Option 2 stays open if a real deployment needs a runtime check; it must use a different model
  family from the evaluation judge and would add a model call to every answer, and its latency to
  voice turns (already over budget).
- The labelled link set and the script make the comparison repeatable for any future verifier.
