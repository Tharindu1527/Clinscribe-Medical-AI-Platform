# Phase 2 ablation report

209 answerable golden questions (golden set v1). Recall is answer-level and
quote-based: a chunk that gives the same answer in other words counts as a miss (2 of 6
sampled misses in task 4), so every recall figure is a lower bound. Each step is compared
with the system it was added to; 95% paired bootstrap intervals. Latency is per query on
CPU (query embedding, retrieval and reranking), p50/p95, all systems re-timed back to
back on 2026-10-13.

Step 1, dense-only baseline: recall@10 0.809, MRR@10 0.562, nDCG@10 0.583; p50 106 ms, p95 143 ms.

| step | added | vs | recall@10 | difference [95% CI] | MRR@10 difference | nDCG@10 difference | p50 / p95 ms | outcome |
|---|---|---|---|---|---|---|---|---|
| 2 | BM25 + RRF (hybrid) (`hybrid`) | `dense` | 0.813 | +0.005 [-0.048, +0.057] | -0.028 [-0.074, +0.017] | -0.012 [-0.053, +0.027] | 106 / 133 | kept: complementary pool for the reranker |
| 3a | cross-encoder rerank (`hybrid_ce`) | `hybrid` | 0.833 | +0.019 [-0.024, +0.062] | +0.018 [-0.033, +0.068] | +0.026 [-0.016, +0.068] | 2704 / 3239 | rejected: no gain, ~3 s/query |
| 3b | ColBERT rerank (`hybrid_colbert`) | `hybrid` | 0.876 | +0.062 [+0.019, +0.105] | +0.074 [+0.031, +0.117] | +0.067 [+0.030, +0.104] | 156 / 202 | kept (ADR-0006) |
| 4 | contextual retrieval (`hybrid_colbert_ctx`) | `hybrid_colbert` | 0.909 | +0.033 [-0.010, +0.077] | +0.073 [+0.028, +0.118] | +0.057 [+0.018, +0.095] | 159 / 206 | kept |
| 5 | late chunking (instead of 4) (`hybrid_colbert_late`) | `hybrid_colbert_ctx` | 0.861 | -0.048 [-0.091, -0.005] | -0.081 [-0.127, -0.036] | -0.068 [-0.106, -0.028] | 166 / 235 | rejected |
| 6 | GraphRAG candidates (`graph_ctx`) | `hybrid_colbert_ctx` | 0.914 | +0.005 [+0.000, +0.014] | +0.005 [+0.000, +0.014] | +0.005 [+0.000, +0.014] | 163 / 207 | facts kept, candidates not |
| re-check | BM25 removed from the chosen pipeline (`dense_colbert_ctx`) | `hybrid_colbert_ctx` | 0.890 | -0.019 [-0.043, +0.005] | -0.008 [-0.024, +0.005] | -0.006 [-0.020, +0.007] | 136 / 174 | BM25 kept (ADR-0006 re-check) |
| chosen | chosen pipeline vs dense-only (`hybrid_colbert_ctx`) | `dense` | 0.909 | +0.100 [+0.053, +0.148] | +0.119 [+0.068, +0.169] | +0.111 [+0.069, +0.155] | 159 / 206 | gate |

Not in this table: step 7 (adaptive routing) and Self-RAG / CRAG move to Phase 3 (they
need the agent loop). Vector store: ADR-0007 (Qdrant kept; pgvector measured).

## Answers (60-question stratified subset, task 10)

Generator Groq gpt-oss-20b, judge gpt-oss-120b; faithfulness and citation precision on
questions both systems answered, correctness on all answerable questions.

| candidate vs dense | correctness | faithfulness | citation precision |
|---|---|---|---|
| `hybrid_colbert` | 0.860 (+0.100 [+0.010, +0.190], n 50) | 0.943 (+0.006 [-0.073, +0.085], n 41) | 0.870 (-0.056 [-0.150, +0.042], n 41) |
| `hybrid_colbert_ctx` | 0.910 (+0.150 [+0.050, +0.260], n 50) | 0.941 (+0.004 [-0.049, +0.069], n 41) | 0.875 (-0.051 [-0.124, +0.028], n 41) |

Graph-only check (10 Major DDInter pairs no chunk names together): text + DDInter facts
answered 10/10 with faithfulness 0.95, text only 4/10 with 0.62 (`answers_graph_facts.md`).

## Phase 2 gate

| criterion | evidence | result |
|---|---|---|
| recall@10: chosen beats dense-only | +0.100 [+0.053, +0.148] | PASS |
| answer correctness: chosen beats dense-only | +0.150 [+0.050, +0.260], n 50 | PASS |
| faithfulness: chosen not worse than dense-only by > 0.05 | +0.004 [-0.049, +0.069], n 41 | PASS |
