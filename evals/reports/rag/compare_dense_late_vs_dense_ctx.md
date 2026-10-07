# `dense_late` vs `dense_ctx`

Paired bootstrap over 209 answerable questions (10,000 resamples, seed 42).

| metric | baseline | candidate | difference | 95% CI | better? |
|---|---|---|---|---|---|
| recall@1 | 0.469 | 0.340 | -0.129 | [-0.196, -0.062] | no |
| recall@5 | 0.746 | 0.646 | -0.100 | [-0.153, -0.048] | no |
| recall@10 | 0.842 | 0.727 | -0.115 | [-0.167, -0.067] | no |
| mrr@10 | 0.592 | 0.458 | -0.134 | [-0.183, -0.085] | no |
| ndcg@10 | 0.623 | 0.502 | -0.121 | [-0.162, -0.081] | no |

| found within | baseline only | candidate only | both | either |
|---|---|---|---|---|
| top 10 | 27 | 3 | 149 | 179 (0.856) |
| top 20 | 18 | 4 | 169 | 191 (0.914) |
