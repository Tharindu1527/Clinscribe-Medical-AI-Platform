# Ask router (ablation step 7)

235 golden questions. The interaction cues come from the Phase 2 graph router,
whose rules were widened after reading these questions, so recall here is optimistic.

| rule | interaction questions routed agentic | other questions routed agentic |
|---|---|---|
| comparison wording only | 2/20 | 9/215 |
| chosen: + interaction cues, several questions, long questions | 14/20 | 25/215 |

| question type | fast | agentic |
|---|---|---|
| adverse_effect | 21 | 3 |
| contraindication | 18 | 4 |
| dose | 35 | 1 |
| fact | 60 | 7 |
| interaction | 6 | 14 |
| recommendation | 56 | 10 |

Cost per question: fast = 1 model call (answer); agentic = 2-3 (grading, at most one
rewrite, answer) plus one druggraph-mcp call when two or more drug names are present.
Answer quality fast vs agentic was not measured on the free-tier budget; the agentic
path's measured value so far is the graph-only check (task 10: 10/10 vs 4/10 answered).
