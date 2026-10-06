# `hybrid_colbert_ctx` vs `hybrid_colbert`

Paired bootstrap over 209 answerable questions (10,000 resamples, seed 42).

| metric | baseline | candidate | difference | 95% CI | better? |
|---|---|---|---|---|---|
| recall@1 | 0.469 | 0.565 | +0.096 | [+0.038, +0.158] | yes |
| recall@5 | 0.789 | 0.828 | +0.038 | [-0.014, +0.091] | not shown |
| recall@10 | 0.876 | 0.909 | +0.033 | [-0.010, +0.077] | not shown |
| mrr@10 | 0.607 | 0.680 | +0.073 | [+0.028, +0.118] | yes |
| ndcg@10 | 0.638 | 0.695 | +0.057 | [+0.018, +0.095] | yes |

| found within | baseline only | candidate only | both | either |
|---|---|---|---|---|
| top 10 | 7 | 14 | 176 | 197 (0.943) |
| top 20 | 4 | 7 | 189 | 200 (0.957) |
