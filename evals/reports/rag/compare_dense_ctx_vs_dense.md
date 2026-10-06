# `dense_ctx` vs `dense`

Paired bootstrap over 209 answerable questions (10,000 resamples, seed 42).

| metric | baseline | candidate | difference | 95% CI | better? |
|---|---|---|---|---|---|
| recall@1 | 0.435 | 0.469 | +0.033 | [-0.019, +0.091] | not shown |
| recall@5 | 0.722 | 0.746 | +0.024 | [-0.029, +0.077] | not shown |
| recall@10 | 0.809 | 0.842 | +0.033 | [-0.010, +0.077] | not shown |
| mrr@10 | 0.562 | 0.592 | +0.030 | [-0.009, +0.069] | not shown |
| ndcg@10 | 0.583 | 0.623 | +0.040 | [+0.006, +0.074] | yes |

| found within | baseline only | candidate only | both | either |
|---|---|---|---|---|
| top 10 | 7 | 14 | 162 | 183 (0.876) |
| top 20 | 4 | 8 | 179 | 191 (0.914) |
