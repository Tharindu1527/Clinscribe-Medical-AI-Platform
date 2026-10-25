# Answers: `hybrid_colbert_ctx_v2` vs `hybrid_colbert_ctx`

60 questions (stratified subset of the golden set); generator and judge per prompts/answer_cited.yaml and prompts/judge_citations.yaml; 95% paired bootstrap.

| metric | baseline | candidate | difference | 95% CI | n pairs | better? |
|---|---|---|---|---|---|---|
| faithfulness | 0.933 | 0.968 | +0.035 | [-0.030, +0.096] | 47 | not shown |
| citation_precision | 0.865 | 0.963 | +0.098 | [+0.041, +0.158] | 47 | yes |
| correctness | 0.910 | 0.870 | -0.040 | [-0.110, +0.020] | 50 | not shown |

| system | answered | false abstain (answerable) | correct abstain (unanswerable) | judge errors |
|---|---|---|---|---|
| hybrid_colbert_ctx | 49/60 | 0.02 | 1.0 | 0 |
| hybrid_colbert_ctx_v2 | 48/60 | 0.06 | 0.9 | 0 |
