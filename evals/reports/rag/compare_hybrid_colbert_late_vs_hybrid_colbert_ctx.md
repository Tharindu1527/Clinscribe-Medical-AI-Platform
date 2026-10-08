# `hybrid_colbert_late` vs `hybrid_colbert_ctx`

Paired bootstrap over 209 answerable questions (10,000 resamples, seed 42).

| metric | baseline | candidate | difference | 95% CI | better? |
|---|---|---|---|---|---|
| recall@1 | 0.565 | 0.464 | -0.100 | [-0.163, -0.038] | no |
| recall@5 | 0.828 | 0.785 | -0.043 | [-0.096, +0.010] | not shown |
| recall@10 | 0.909 | 0.861 | -0.048 | [-0.091, -0.005] | no |
| mrr@10 | 0.680 | 0.599 | -0.081 | [-0.127, -0.036] | no |
| ndcg@10 | 0.695 | 0.627 | -0.068 | [-0.106, -0.028] | no |

| found within | baseline only | candidate only | both | either |
|---|---|---|---|---|
| top 10 | 16 | 6 | 174 | 196 (0.938) |
| top 20 | 10 | 3 | 186 | 199 (0.952) |
