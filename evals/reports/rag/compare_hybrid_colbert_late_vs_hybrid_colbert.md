# `hybrid_colbert_late` vs `hybrid_colbert`

Paired bootstrap over 209 answerable questions (10,000 resamples, seed 42).

| metric | baseline | candidate | difference | 95% CI | better? |
|---|---|---|---|---|---|
| recall@1 | 0.469 | 0.464 | -0.005 | [-0.014, +0.000] | not shown |
| recall@5 | 0.789 | 0.785 | -0.005 | [-0.024, +0.010] | not shown |
| recall@10 | 0.876 | 0.861 | -0.014 | [-0.033, +0.000] | not shown |
| mrr@10 | 0.607 | 0.599 | -0.008 | [-0.021, +0.001] | not shown |
| ndcg@10 | 0.638 | 0.627 | -0.011 | [-0.024, -0.001] | no |

| found within | baseline only | candidate only | both | either |
|---|---|---|---|---|
| top 10 | 3 | 0 | 180 | 183 (0.876) |
| top 20 | 4 | 0 | 189 | 193 (0.923) |
