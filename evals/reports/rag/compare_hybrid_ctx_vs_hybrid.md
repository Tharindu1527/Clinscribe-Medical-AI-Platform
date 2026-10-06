# `hybrid_ctx` vs `hybrid`

Paired bootstrap over 209 answerable questions (10,000 resamples, seed 42).

| metric | baseline | candidate | difference | 95% CI | better? |
|---|---|---|---|---|---|
| recall@1 | 0.407 | 0.512 | +0.105 | [+0.048, +0.167] | yes |
| recall@5 | 0.679 | 0.756 | +0.077 | [+0.024, +0.129] | yes |
| recall@10 | 0.813 | 0.847 | +0.033 | [-0.010, +0.081] | not shown |
| mrr@10 | 0.533 | 0.617 | +0.084 | [+0.042, +0.128] | yes |
| ndcg@10 | 0.571 | 0.643 | +0.073 | [+0.038, +0.110] | yes |

| found within | baseline only | candidate only | both | either |
|---|---|---|---|---|
| top 10 | 8 | 15 | 162 | 185 (0.885) |
| top 20 | 4 | 10 | 185 | 199 (0.952) |
