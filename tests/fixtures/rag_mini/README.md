# Mini retrieval fixture (CI regression check)

Built by `uv run python -m evals.rag.fixture` (Phase 2 task 12) and read by
`tests/unit/test_rag_regression.py`. It lets CI recompute dense, BM25 and hybrid (RRF) retrieval
metrics without the corpus, Qdrant or model downloads.

| File | Content |
|---|---|
| `questions.jsonl` | 100 golden questions (20 per clinical area), FDA and PMC sources only, with gold chunk ids |
| `chunks.jsonl` | 1,205 corpus chunks: the gold chunks plus the top 10 of the stored dense and BM25 runs |
| `chunk_vectors.npy`, `query_vectors.npy` | ModernBERT Embed vectors (float16) for those chunks and questions |
| `thresholds.json` | metrics measured at build time, and thresholds 0.01 below them |

Recall is answer-level and quote-based, so it is a lower bound (see `evals/reports/rag/ablation.md`).

## Licences

Chunk text is quoted from public sources, each row carrying its source URL and licence:

- openFDA drug labels: CC0 1.0 (483 chunks).
- PubMed Central Open Access articles: CC BY 4.0 (566), CC0 1.0 (122), CC BY 3.0 (29) and CC BY 2.5 (5).
  Attribution: each chunk's `title` and `url` name the article.

WHO guideline text (CC BY-NC-SA 3.0 IGO) is deliberately excluded. See `data/LICENSES.md` for the
licence checks of every corpus source.
