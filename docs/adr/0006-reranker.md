# ADR-0006: Reranker — ColBERT late interaction over the hybrid candidate pool

Status: Proposed · Date: 2026-10-06

## Context

Ablation step 3 (SPEC §6, §11) compares a cross-encoder and a ColBERT reranker on top of the first
stage. Step 2 showed that hybrid search (dense + BM25 with RRF) does not beat dense at the top ranks,
but its candidate pool holds more answers (in the top 20: 0.904 vs 0.876), so both pools were reranked.

Constraints: CPU only (the Phase 2 default), a voice budget that needs fast retrieval (TTFA p95
< 1.5 s for the whole turn, Phase 4), and no model that needs remote code (ADR-0005).

Setup: 30 candidates per question from the first stage, reordered by the reranker.

- **Cross-encoder** `cross-encoder/ms-marco-MiniLM-L6-v2`: 22M parameters, Apache-2.0, through
  sentence-transformers.
- **ColBERT** `answerdotai/answerai-colbert-small-v1`: 33M parameters, Apache-2.0, Stanford ColBERT
  format.
  - PyLate (the planned library) pins sentence-transformers 5.3 and transformers ≤ 5.3, against 6.1
    and 5.18 here, and would pull in datasets, accelerate, pandas and two compiled index libraries.
    So the encoding is implemented in `retrieval/colbert.py` (about 60 lines).
  - It was checked against the authors' ONNX export of the same model: max |difference| 2.6e-7 on
    query and document vectors (`evals/rag/colbert_parity.py`).
  - Document token vectors are precomputed once: 8,104 chunks, 1.7M vectors, 326 MB as float16 on D:,
    14 minutes on CPU (9.7 chunks/s).

Results on the golden set (209 answerable questions; difference vs dense with 95% paired-bootstrap CI;
latency per query on CPU, warm):

| system | recall@10 | MRR@10 | nDCG@10 | p50 / p95 ms |
|---|---|---|---|---|
| dense (baseline) | 0.809 | 0.562 | 0.583 | 94 / 150 |
| dense + cross-encoder | 0.828 (+0.019, CI [−0.024, +0.067]) | 0.563 | 0.598 | 2,750 / 3,912 |
| hybrid + cross-encoder | 0.833 (+0.024, CI [−0.029, +0.077]) | 0.551 | 0.596 | 2,497 / 2,923 |
| dense + ColBERT | 0.852 (+0.043, CI [+0.000, +0.086]) | **0.609 (+0.048, CI [+0.000, +0.095])** | **0.628 (+0.045, CI [+0.007, +0.083])** | 132 / 178 |
| hybrid + ColBERT | **0.876 (+0.067, CI [+0.019, +0.115])** | 0.607 (+0.046, CI [−0.001, +0.093]) | **0.638 (+0.054, CI [+0.015, +0.095])** | 157 / 229 |

Hybrid + ColBERT vs dense + ColBERT: recall@10 +0.024 (CI [−0.005, +0.057]), MRR −0.002: not
shown different.

## Options

1. **Cross-encoder (MS MARCO MiniLM).** No gain shown on any metric, and 2.5–3.9 s per query on CPU
   because all 30 pairs are scored at query time: this alone breaks the voice budget. A biomedical
   cross-encoder (e.g. NCBI MedCPT) could do better on clinical text, but the latency problem stays.
2. **ColBERT over the dense pool.** Better MRR and nDCG with CIs above zero; the recall@10 CI touches
   zero. Simplest pipeline (no BM25 index).
3. **ColBERT over the hybrid pool.** The only configuration whose recall@10 gain over dense is shown
   (+0.067), and the best nDCG. It costs about 25 ms more than option 2, plus the in-process BM25
   index. Its edge over option 2 is not significant.
4. **No reranker.** Keeps 94 ms, but leaves the measured gains unused.

## Decision

Option 3, **hybrid search + ColBERT reranking**, as the best pipeline so far for the next ablation
steps (contextual retrieval, late chunking, GraphRAG). ColBERT replaces the cross-encoder: it is
better on every metric and about 20 times faster at query time, because document vectors are
precomputed.

BM25 stays because recall is the ceiling for everything after retrieval, and the hybrid pool is the
only setup with a shown recall@10 gain. Its benefit over dense + ColBERT is not significant, so
dropping it is reconsidered in the final ablation report (task 12) with pooled relevance judgements.

## Consequences

- Retrieval p95 is about 230 ms on CPU, a small share of the 1.5 s TTFA budget.
- The ColBERT store must be rebuilt (`just index-colbert`, 14 min) whenever the corpus changes, like
  the dense index. It is memory-mapped, so it does not need 326 MB of RAM at start-up.
- Steps 4–5 change chunk text, so they also re-encode the ColBERT store, about 14 min each.
- ColBERT scores do not separate answerable from unanswerable questions: the median top-1 score is
  30.8 vs 30.3. Abstention ("no evidence found") has to come from the generation and citation check
  (task 10), not from a retrieval score threshold.
- The cross-encoder code stays (`retrieval/rerank.py`) for a later biomedical model comparison; it
  is not in the default pipeline.
