# `bm25_ctx` vs `bm25`

Paired bootstrap over 209 answerable questions (10,000 resamples, seed 42).

| metric | baseline | candidate | difference | 95% CI | better? |
|---|---|---|---|---|---|
| recall@1 | 0.325 | 0.411 | +0.086 | [+0.038, +0.134] | yes |
| recall@5 | 0.593 | 0.703 | +0.110 | [+0.057, +0.163] | yes |
| recall@10 | 0.699 | 0.799 | +0.100 | [+0.057, +0.148] | yes |
| mrr@10 | 0.441 | 0.533 | +0.092 | [+0.055, +0.130] | yes |
| ndcg@10 | 0.481 | 0.576 | +0.095 | [+0.062, +0.130] | yes |

| found within | baseline only | candidate only | both | either |
|---|---|---|---|---|
| top 10 | 2 | 23 | 144 | 169 (0.809) |
| top 20 | 1 | 21 | 162 | 184 (0.880) |
