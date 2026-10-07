# `dense_late` vs `dense`

Paired bootstrap over 209 answerable questions (10,000 resamples, seed 42).

| metric | baseline | candidate | difference | 95% CI | better? |
|---|---|---|---|---|---|
| recall@1 | 0.435 | 0.340 | -0.096 | [-0.163, -0.029] | no |
| recall@5 | 0.722 | 0.646 | -0.077 | [-0.124, -0.029] | no |
| recall@10 | 0.809 | 0.727 | -0.081 | [-0.129, -0.038] | no |
| mrr@10 | 0.562 | 0.458 | -0.104 | [-0.149, -0.058] | no |
| ndcg@10 | 0.583 | 0.502 | -0.081 | [-0.117, -0.045] | no |

| found within | baseline only | candidate only | both | either |
|---|---|---|---|---|
| top 10 | 21 | 4 | 148 | 173 (0.828) |
| top 20 | 12 | 2 | 171 | 185 (0.885) |
