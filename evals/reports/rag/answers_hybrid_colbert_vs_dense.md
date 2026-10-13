# Answers: `hybrid_colbert` vs `dense`

60 questions (stratified subset of the golden set); generator and judge per prompts/answer_cited.yaml and prompts/judge_citations.yaml; 95% paired bootstrap.

| metric | baseline | candidate | difference | 95% CI | n pairs | better? |
|---|---|---|---|---|---|---|
| faithfulness | 0.937 | 0.943 | +0.006 | [-0.073, +0.085] | 41 | not shown |
| citation_precision | 0.926 | 0.870 | -0.056 | [-0.150, +0.042] | 41 | not shown |
| correctness | 0.760 | 0.860 | +0.100 | [+0.010, +0.190] | 50 | yes |

| system | answered | false abstain (answerable) | correct abstain (unanswerable) | judge errors |
|---|---|---|---|---|
| dense | 41/60 | 0.18 | 1.0 | 0 |
| hybrid_colbert | 47/60 | 0.06 | 1.0 | 0 |
