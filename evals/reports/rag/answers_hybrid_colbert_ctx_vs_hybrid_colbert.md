# Answers: `hybrid_colbert_ctx` vs `hybrid_colbert`

60 questions (stratified subset of the golden set); generator and judge per prompts/answer_cited.yaml and prompts/judge_citations.yaml; 95% paired bootstrap.

| metric | baseline | candidate | difference | 95% CI | n pairs | better? |
|---|---|---|---|---|---|---|
| faithfulness | 0.928 | 0.937 | +0.009 | [-0.067, +0.094] | 46 | not shown |
| citation_precision | 0.863 | 0.868 | +0.005 | [-0.078, +0.095] | 46 | not shown |
| correctness | 0.860 | 0.910 | +0.050 | [-0.030, +0.140] | 50 | not shown |

| system | answered | false abstain (answerable) | correct abstain (unanswerable) | judge errors |
|---|---|---|---|---|
| hybrid_colbert | 47/60 | 0.06 | 1.0 | 0 |
| hybrid_colbert_ctx | 49/60 | 0.02 | 1.0 | 0 |
