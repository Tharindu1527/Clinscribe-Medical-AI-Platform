# `graph_ctx` vs `hybrid_colbert_ctx`

Paired bootstrap over 19 answerable questions (subset: qtype=interaction) (10,000 resamples, seed 42).

| metric | baseline | candidate | difference | 95% CI | better? |
|---|---|---|---|---|---|
| recall@1 | 0.526 | 0.526 | +0.000 | [+0.000, +0.000] | not shown |
| recall@5 | 0.737 | 0.737 | +0.000 | [+0.000, +0.000] | not shown |
| recall@10 | 0.895 | 0.895 | +0.000 | [+0.000, +0.000] | not shown |
| mrr@10 | 0.627 | 0.627 | +0.000 | [+0.000, +0.000] | not shown |
| ndcg@10 | 0.655 | 0.655 | +0.000 | [+0.000, +0.000] | not shown |

| found within | baseline only | candidate only | both | either |
|---|---|---|---|---|
| top 10 | 0 | 0 | 17 | 17 (0.895) |
| top 20 | 0 | 0 | 18 | 18 (0.947) |
