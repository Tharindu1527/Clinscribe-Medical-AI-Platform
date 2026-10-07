# `hybrid_colbert_ctx` vs `dense`

Paired bootstrap over 209 answerable questions (10,000 resamples, seed 42).

| metric | baseline | candidate | difference | 95% CI | better? |
|---|---|---|---|---|---|
| recall@1 | 0.435 | 0.565 | +0.129 | [+0.062, +0.196] | yes |
| recall@5 | 0.722 | 0.828 | +0.105 | [+0.048, +0.167] | yes |
| recall@10 | 0.809 | 0.909 | +0.100 | [+0.053, +0.148] | yes |
| mrr@10 | 0.562 | 0.680 | +0.119 | [+0.068, +0.169] | yes |
| ndcg@10 | 0.583 | 0.695 | +0.111 | [+0.069, +0.155] | yes |

| found within | baseline only | candidate only | both | either |
|---|---|---|---|---|
| top 10 | 4 | 25 | 165 | 194 (0.928) |
| top 20 | 2 | 15 | 181 | 198 (0.947) |
