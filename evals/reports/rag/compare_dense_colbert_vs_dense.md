# `dense_colbert` vs `dense`

Paired bootstrap over 209 answerable questions (10,000 resamples, seed 42).

| metric | baseline | candidate | difference | 95% CI | better? |
|---|---|---|---|---|---|
| recall@1 | 0.435 | 0.478 | +0.043 | [-0.024, +0.110] | not shown |
| recall@5 | 0.722 | 0.785 | +0.062 | [+0.014, +0.110] | yes |
| recall@10 | 0.809 | 0.852 | +0.043 | [+0.000, +0.086] | not shown |
| mrr@10 | 0.562 | 0.609 | +0.048 | [+0.000, +0.095] | yes |
| ndcg@10 | 0.583 | 0.628 | +0.045 | [+0.007, +0.083] | yes |

| found within | baseline only | candidate only | both | either |
|---|---|---|---|---|
| top 10 | 6 | 15 | 163 | 184 (0.880) |
| top 20 | 3 | 7 | 180 | 190 (0.909) |
