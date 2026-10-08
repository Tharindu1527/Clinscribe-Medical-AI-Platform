# `graph_ctx` vs `hybrid_colbert_ctx`

Paired bootstrap over 28 answerable questions (subset: routed) (10,000 resamples, seed 42).

| metric | baseline | candidate | difference | 95% CI | better? |
|---|---|---|---|---|---|
| recall@1 | 0.571 | 0.607 | +0.036 | [+0.000, +0.107] | not shown |
| recall@5 | 0.786 | 0.821 | +0.036 | [+0.000, +0.107] | not shown |
| recall@10 | 0.893 | 0.929 | +0.036 | [+0.000, +0.107] | not shown |
| mrr@10 | 0.676 | 0.712 | +0.036 | [+0.000, +0.107] | not shown |
| ndcg@10 | 0.691 | 0.727 | +0.036 | [+0.000, +0.107] | not shown |

| found within | baseline only | candidate only | both | either |
|---|---|---|---|---|
| top 10 | 0 | 1 | 25 | 26 (0.929) |
| top 20 | 0 | 1 | 26 | 27 (0.964) |
