# `hybrid` vs `dense`

Paired bootstrap over 209 answerable questions (10,000 resamples, seed 42).

| metric | baseline | candidate | difference | 95% CI | better? |
|---|---|---|---|---|---|
| recall@1 | 0.435 | 0.407 | -0.029 | [-0.091, +0.033] | not shown |
| recall@5 | 0.722 | 0.679 | -0.043 | [-0.100, +0.014] | not shown |
| recall@10 | 0.809 | 0.813 | +0.005 | [-0.048, +0.057] | not shown |
| mrr@10 | 0.562 | 0.533 | -0.028 | [-0.074, +0.017] | not shown |
| ndcg@10 | 0.583 | 0.571 | -0.012 | [-0.053, +0.027] | not shown |

| found within | baseline only | candidate only | both | either |
|---|---|---|---|---|
| top 10 | 14 | 15 | 155 | 184 (0.880) |
| top 20 | 7 | 13 | 176 | 196 (0.938) |
