# `hybrid_colbert_ctx` vs `dense_colbert_ctx`

Paired bootstrap over 209 answerable questions (10,000 resamples, seed 42).

| metric | baseline | candidate | difference | 95% CI | better? |
|---|---|---|---|---|---|
| recall@1 | 0.560 | 0.565 | +0.005 | [-0.010, +0.019] | not shown |
| recall@5 | 0.823 | 0.828 | +0.005 | [-0.019, +0.029] | not shown |
| recall@10 | 0.890 | 0.909 | +0.019 | [-0.005, +0.043] | not shown |
| mrr@10 | 0.672 | 0.680 | +0.008 | [-0.005, +0.024] | not shown |
| ndcg@10 | 0.689 | 0.695 | +0.006 | [-0.007, +0.020] | not shown |

| found within | baseline only | candidate only | both | either |
|---|---|---|---|---|
| top 10 | 1 | 5 | 185 | 191 (0.914) |
| top 20 | 1 | 5 | 191 | 197 (0.943) |
