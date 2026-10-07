# `hybrid_colbert` vs `dense`

Paired bootstrap over 209 answerable questions (10,000 resamples, seed 42).

| metric | baseline | candidate | difference | 95% CI | better? |
|---|---|---|---|---|---|
| recall@1 | 0.435 | 0.469 | +0.033 | [-0.033, +0.100] | not shown |
| recall@5 | 0.722 | 0.789 | +0.067 | [+0.014, +0.120] | yes |
| recall@10 | 0.809 | 0.876 | +0.067 | [+0.019, +0.115] | yes |
| mrr@10 | 0.562 | 0.607 | +0.046 | [-0.001, +0.093] | not shown |
| ndcg@10 | 0.583 | 0.638 | +0.054 | [+0.015, +0.095] | yes |

| found within | baseline only | candidate only | both | either |
|---|---|---|---|---|
| top 10 | 6 | 20 | 163 | 189 (0.904) |
| top 20 | 4 | 14 | 179 | 197 (0.943) |
