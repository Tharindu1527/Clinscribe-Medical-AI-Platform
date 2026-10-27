# Answers: `hybrid_colbert_ctx_low` vs `hybrid_colbert_ctx`

60 questions (stratified subset of the golden set); generator and judge per prompts/answer_cited.yaml and prompts/judge_citations.yaml; 95% paired bootstrap.

| metric | baseline | candidate | difference | 95% CI | n pairs | better? |
|---|---|---|---|---|---|---|
| faithfulness | 0.931 | 0.942 | +0.011 | [-0.062, +0.076] | 46 | not shown |
| citation_precision | 0.862 | 0.895 | +0.033 | [-0.045, +0.106] | 46 | not shown |
| correctness | 0.910 | 0.890 | -0.020 | [-0.080, +0.030] | 50 | not shown |

| system | answered | false abstain (answerable) | correct abstain (unanswerable) | judge errors |
|---|---|---|---|---|
| hybrid_colbert_ctx | 49/60 | 0.02 | 1.0 | 0 |
| hybrid_colbert_ctx_low | 47/60 | 0.08 | 0.9 | 0 |
