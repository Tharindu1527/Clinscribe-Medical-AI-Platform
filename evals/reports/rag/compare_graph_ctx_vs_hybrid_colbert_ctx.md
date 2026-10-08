# `graph_ctx` vs `hybrid_colbert_ctx`

Paired bootstrap over 209 answerable questions (10,000 resamples, seed 42).

| metric | baseline | candidate | difference | 95% CI | better? |
|---|---|---|---|---|---|
| recall@1 | 0.565 | 0.569 | +0.005 | [+0.000, +0.014] | not shown |
| recall@5 | 0.828 | 0.833 | +0.005 | [+0.000, +0.014] | not shown |
| recall@10 | 0.909 | 0.914 | +0.005 | [+0.000, +0.014] | not shown |
| mrr@10 | 0.680 | 0.685 | +0.005 | [+0.000, +0.014] | not shown |
| ndcg@10 | 0.695 | 0.699 | +0.005 | [+0.000, +0.014] | not shown |

| found within | baseline only | candidate only | both | either |
|---|---|---|---|---|
| top 10 | 0 | 1 | 190 | 191 (0.914) |
| top 20 | 0 | 1 | 196 | 197 (0.943) |
