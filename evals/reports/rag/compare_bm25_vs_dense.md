# `bm25` vs `dense`

Paired bootstrap over 209 answerable questions (10,000 resamples, seed 42).

| metric | baseline | candidate | difference | 95% CI | better? |
|---|---|---|---|---|---|
| recall@1 | 0.435 | 0.325 | -0.110 | [-0.187, -0.033] | no |
| recall@5 | 0.722 | 0.593 | -0.129 | [-0.196, -0.062] | no |
| recall@10 | 0.809 | 0.699 | -0.110 | [-0.182, -0.038] | no |
| mrr@10 | 0.562 | 0.441 | -0.121 | [-0.181, -0.060] | no |
| ndcg@10 | 0.583 | 0.481 | -0.102 | [-0.159, -0.044] | no |

| found within | baseline only | candidate only | both | either |
|---|---|---|---|---|
| top 10 | 42 | 19 | 127 | 188 (0.900) |
| top 20 | 34 | 14 | 149 | 197 (0.943) |
