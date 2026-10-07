# `hybrid_ce` vs `dense`

Paired bootstrap over 209 answerable questions (10,000 resamples, seed 42).

| metric | baseline | candidate | difference | 95% CI | better? |
|---|---|---|---|---|---|
| recall@1 | 0.435 | 0.426 | -0.010 | [-0.077, +0.062] | not shown |
| recall@5 | 0.722 | 0.708 | -0.014 | [-0.072, +0.043] | not shown |
| recall@10 | 0.809 | 0.833 | +0.024 | [-0.029, +0.077] | not shown |
| mrr@10 | 0.562 | 0.551 | -0.010 | [-0.061, +0.041] | not shown |
| ndcg@10 | 0.583 | 0.596 | +0.013 | [-0.029, +0.057] | not shown |

| found within | baseline only | candidate only | both | either |
|---|---|---|---|---|
| top 10 | 13 | 18 | 156 | 187 (0.895) |
| top 20 | 6 | 15 | 177 | 198 (0.947) |
