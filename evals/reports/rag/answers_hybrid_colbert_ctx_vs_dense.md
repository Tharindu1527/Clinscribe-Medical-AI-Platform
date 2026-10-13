# Answers: `hybrid_colbert_ctx` vs `dense`

60 questions (stratified subset of the golden set); generator and judge per prompts/answer_cited.yaml and prompts/judge_citations.yaml; 95% paired bootstrap.

| metric | baseline | candidate | difference | 95% CI | n pairs | better? |
|---|---|---|---|---|---|---|
| faithfulness | 0.937 | 0.941 | +0.004 | [-0.049, +0.069] | 41 | not shown |
| citation_precision | 0.926 | 0.875 | -0.051 | [-0.124, +0.028] | 41 | not shown |
| correctness | 0.760 | 0.910 | +0.150 | [+0.050, +0.260] | 50 | yes |

| system | answered | false abstain (answerable) | correct abstain (unanswerable) | judge errors |
|---|---|---|---|---|
| dense | 41/60 | 0.18 | 1.0 | 0 |
| hybrid_colbert_ctx | 49/60 | 0.02 | 1.0 | 0 |
