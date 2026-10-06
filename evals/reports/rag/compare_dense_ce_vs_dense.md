# `dense_ce` vs `dense`

Paired bootstrap over 209 answerable questions (10,000 resamples, seed 42).

| metric | baseline | candidate | difference | 95% CI | better? |
|---|---|---|---|---|---|
| recall@1 | 0.435 | 0.440 | +0.005 | [-0.067, +0.081] | not shown |
| recall@5 | 0.722 | 0.713 | -0.010 | [-0.062, +0.048] | not shown |
| recall@10 | 0.809 | 0.828 | +0.019 | [-0.024, +0.067] | not shown |
| mrr@10 | 0.562 | 0.563 | +0.001 | [-0.051, +0.054] | not shown |
| ndcg@10 | 0.583 | 0.598 | +0.015 | [-0.027, +0.058] | not shown |

| found within | baseline only | candidate only | both | either |
|---|---|---|---|---|
| top 10 | 10 | 14 | 159 | 183 (0.876) |
| top 20 | 3 | 6 | 180 | 189 (0.904) |
