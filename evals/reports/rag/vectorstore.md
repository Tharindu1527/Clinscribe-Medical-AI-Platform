# Vector stores: Qdrant vs pgvector

209 answerable golden questions; contextual chunk vectors (8,104 x 768, ModernBERT Embed), the same query vectors for every system; latency is store-only (query embedding excluded), 3 warm passes, client on the host, stores in Docker. HNSW m 16, ef_construct 100 in both. Overlap@10 = share of the exact 10 nearest neighbours returned. Paired 95% bootstrap vs `qdrant` (the deployed collection).

| system | recall@10 | nDCG@10 | overlap@10 vs exact | p50 ms | p95 ms | recall@10 vs qdrant |
|---|---|---|---|---|---|---|
| qdrant | 0.842 | 0.623 | 1.000 | 7.3 | 13.7 | — |
| qdrant_hnsw_ef40 | 0.842 | 0.624 | 0.998 | 7.5 | 17.8 | +0.000 [+0.000, +0.000] |
| qdrant_hnsw_ef100 | 0.842 | 0.623 | 1.000 | 9.5 | 15.7 | +0.000 [+0.000, +0.000] |
| pgvector_exact | 0.842 | 0.623 | 1.000 | 74.7 | 107.4 | +0.000 [+0.000, +0.000] |
| pgvector_hnsw_ef40 | 0.818 | 0.607 | 0.980 | 5.7 | 9.3 | -0.024 [-0.048, -0.005] |
| pgvector_hnsw_ef100 | 0.842 | 0.623 | 0.999 | 7.2 | 11.9 | +0.000 [+0.000, +0.000] |

Build and footprint:

- deployed Qdrant collection: 0 vectors HNSW-indexed across 6 segments (below the indexing threshold: exact search)
- Qdrant HNSW copy: upsert 11.2 s, index 1.0 s
- pgvector: table already loaded (COPY measured on the first run), HNSW build 4.5 s
- disk: pgvector total 64.8 MB (HNSW 31.7 MB, heap 0.6 MB, the rest TOAST + primary key); Qdrant collection 78.2 MB, HNSW copy 56.0 MB
- container memory after the run: clinscribe-pgvector-1 114MiB / 768MiB, clinscribe-qdrant-1 467.7MiB / 1GiB (Qdrant holds all its collections: raw, contextual, late, HNSW copy)
