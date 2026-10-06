# `hybrid_colbert` vs `dense_colbert`

Paired bootstrap over 209 answerable questions (10,000 resamples, seed 42).

| metric | baseline | candidate | difference | 95% CI | better? |
|---|---|---|---|---|---|
| recall@1 | 0.478 | 0.469 | -0.010 | [-0.029, +0.010] | not shown |
| recall@5 | 0.785 | 0.789 | +0.005 | [-0.024, +0.033] | not shown |
| recall@10 | 0.852 | 0.876 | +0.024 | [-0.005, +0.057] | not shown |
| mrr@10 | 0.609 | 0.607 | -0.002 | [-0.019, +0.013] | not shown |
| ndcg@10 | 0.628 | 0.638 | +0.010 | [-0.006, +0.027] | not shown |

| found within | baseline only | candidate only | both | either |
|---|---|---|---|---|
| top 10 | 3 | 8 | 175 | 186 (0.890) |
| top 20 | 2 | 8 | 185 | 195 (0.933) |
