# ADR-0005: Dense embedding model — ModernBERT Embed instead of jina-embeddings-v2

Status: Proposed · Date: 2026-10-06

## Context

The Phase 2 plan named `jinaai/jina-embeddings-v2-base-en` for the dense baseline because it has an 8k
context, which late chunking (ablation step 5) needs: the whole document is encoded once and token
vectors are pooled per chunk. The model runs in-process on de-identified or public text (ADR-0001).

Checking the model before use (Hugging Face API, 2026-10-06): its config has an `auto_map` to a custom
`JinaBertForMaskedLM` class, so loading it requires `trust_remote_code=True`. That executes Python
downloaded from the model repository at load time — a supply-chain risk in a service that will later
handle clinical queries, and code that is not covered by the lockfile.

## Options

1. **jina-embeddings-v2-base-en with remote code pinned to a commit.** Works, but still runs code from
   outside the lockfile; every revision bump needs a code review of that repository.
2. **nomic-ai/modernbert-embed-base.** Apache-2.0, 149M parameters, 768 dimensions (Matryoshka down to
   256), 8,192-token context; the ModernBERT architecture is built into `transformers`, so it loads with
   `trust_remote_code=False`. Its model card reports MTEB retrieval 52.89 (15 tasks). Needs the prefixes
   `search_query: ` and `search_document: `.
3. **A short-context model (e.g. bge-base-en-v1.5, 512 tokens).** Strong and small, but cannot do late
   chunking over whole documents, so step 5 would need a second model anyway.

## Decision

Option 2. The model is pinned to commit `d556a88e332558790b210f7bdbe87da2fa94a8d8` in
`config/retrieval.yaml` and loaded with `trust_remote_code=False`. It runs on CPU first (plan default),
through `sentence-transformers` for chunk embeddings; late chunking will use the same weights through
`transformers` to get token vectors. Torch is the CPU build from the PyTorch index, in the `rag`
dependency group, which the service image does not install yet.

## Consequences

- No model-repository code runs in this project; the revision pin plus the lockfile define what runs.
- The dense baseline (ablation step 1) and late chunking (step 5) share one model, so step 5 measures the
  chunking method, not a model change.
- The MTEB figure is the vendor's general-domain number; what counts is recall@10 on our golden set
  (task 4). If it is weak on clinical text, a medical model can be compared under the same rules
  (no remote code, licence recorded).
- A model change creates a new Qdrant collection (the name includes the model), so older indexes stay
  available for the ablation report.
