# ADR-0007: Vector store — keep Qdrant; pgvector is a measured fallback

Status: Proposed · Date: 2026-10-13

## Context

Dense retrieval has used Qdrant since Phase 2 task 2. SPEC §10 asks for a comparison with pgvector,
because Postgres already runs in the core stack, so pgvector would remove a service. Memory matters:
core + fhir + rag + voice is estimated at ~10.2 GB against the 10 GB WSL cap (PROGRESS, Phase 4
open question).

Setup (`evals/rag/vectorstore_eval.py`, `just vectorstore`, report `evals/reports/rag/vectorstore.md`):

- Both stores hold the same cached contextual chunk vectors (8,104 × 768, ModernBERT Embed, cosine).
  All systems answer the 209 answerable golden questions from the same query vectors, so only the
  store differs.
- pgvector 0.8.6 on Postgres 16 (`pgvector/pgvector:0.8.6-pg16`), its own container in the
  `vectorstore` profile (768 MB limit), so the comparison never touches app, LiteLLM or HAPI data.
- HNSW with m 16 and ef_construction 100 in both stores (Qdrant's defaults; pgvector's default
  ef_construction is 64).
- Latency is store-only (query embedding excluded): the Python client on the host, the store in
  Docker, 3 warm passes of 209 queries, p50/p95. Qdrant through `qdrant-client` over REST; pgvector
  through psycopg.
- Overlap@10 = share of the exact 10 nearest neighbours (numpy) that the system returns.

A finding on the way: **the deployed Qdrant collection is not HNSW-indexed.** Its 6 segments are
each below Qdrant's 10 MB indexing threshold, so every query is an exact scan (0 of 8,104 vectors
indexed). All Phase 2 dense results so far are therefore exact-search results. Qdrant builds the
index on its own once segments grow past the threshold.

## Options

1. **Keep Qdrant** (as deployed: exact search at this size, HNSW automatically when it grows).
2. **Move to pgvector with HNSW**, in a separate Postgres or in the core Postgres.
3. **pgvector without an index** (exact scan).

## Decision

Option 1: keep Qdrant. pgvector with HNSW at `ef_search` 100 is a measured drop-in if Phase 4
memory forces a service out.

Results (four runs on 2026-10-13; the table is the last run, ranges over all four in brackets):

| System | recall@10 | overlap@10 vs exact | p50 ms | p95 ms |
|---|---|---|---|---|
| Qdrant as deployed (exact) | 0.842 | 1.000 | 7.3 [7.3–8.9] | 13.7 [12.6–16.8] |
| Qdrant HNSW, hnsw_ef 100 | 0.842 | 1.000 | 9.5 [7.0–9.5] | 15.7 [12.1–16.4] |
| pgvector exact (no index) | 0.842 | 1.000 | 74.7 [73.6–79.6] | 107.4 [87.7–115.4] |
| pgvector HNSW, ef_search 40 (default) | 0.818 [0.818–0.828] | 0.980–0.990 | 5.7 [5.6–5.8] | 9.3 [7.6–9.3] |
| pgvector HNSW, ef_search 100 | 0.842 | 0.999–1.000 | 7.2 [6.3–7.2] | 11.9 [8.4–11.9] |

- **Quality is a tie when search is exact or tuned.** Every exact system and both HNSW systems at
  ef 100 return the same golden recall@10 (0.842). pgvector at its default `ef_search` 40 loses
  0.014–0.024 (paired CI excludes 0 in three of four runs) and varies between runs because the graph build
  is not deterministic. If pgvector is used, `ef_search` must be raised.
- **Latency does not decide it.** All indexed or small-scale options answer in under 20 ms at p95,
  next to ~94 ms (p50) for the query embedding and ~45 ms for ColBERT reranking (task 6: hybrid
  p50 111 ms, hybrid + ColBERT 157 ms). pgvector's client
  path is a few ms faster (binary protocol vs Qdrant's REST client; Qdrant's gRPC was not tried).
  pgvector without an index is already ~75 ms at 8k vectors and grows linearly, so it is ruled out.
- **Footprint favours pgvector.** Container memory 114 MB (pgvector) vs 468–533 MB (Qdrant, which
  holds four collections: raw, contextual, late and the HNSW test copy). Disk 64.8 MB in pgvector
  (index 31.7 MB) vs 78.2 MB for the deployed Qdrant collection. Build: pgvector COPY 4.8 s + HNSW
  4.5–5.4 s; Qdrant upsert 10–12 s + HNSW 1 s.

Why keep Qdrant anyway: recall and latency are equal for this corpus, Qdrant is already integrated
and tested (dense index, contextual variant, rag tests), it indexes automatically as data grows, and
it carries payload filtering and native sparse vectors that Phase 3 may use. A move costs a re-index
and new tests for no measured gain. The one real argument for pgvector is memory: removing the
Qdrant container frees what it uses (0.47–0.53 GB measured, partly unused collections), against
some extra memory in Postgres (a separate pgvector container with this table used 114 MB). That
belongs to the Phase 4 memory decision and is recorded here with numbers.

## Consequences

- Qdrant stays the dense store; no pipeline change. The `vectorstore` profile and `pgvector` service
  stay for re-running the comparison only (`just up vectorstore; just vectorstore`); they are not
  part of `just up rag`.
- Phase 4 memory: if core + fhir + rag + voice does not fit, the first options are dropping the
  unused Qdrant collections (raw dense, late) and then moving dense vectors to pgvector in the core
  Postgres with HNSW `ef_search` ≥ 100 (re-run this comparison against that setup first).
- If pgvector is ever adopted, `hnsw.ef_search` is set per query (`SET LOCAL`), as in
  `retrieval/pgvector_store.py`; the default 40 measurably loses recall here.
- Limits: one corpus of 8,104 vectors, one machine, client-side timing. At this size Qdrant's
  deployed collection runs exact search, so its HNSW behaviour at scale was measured on a forced
  copy only. A larger corpus (or the Phase 4 transcripts) should re-run the comparison.
