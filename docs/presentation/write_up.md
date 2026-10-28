# Draft write-up (not yet published — edit and post it yourself)

**Better retrieval didn't make my clinical RAG more faithful. It made it answer more.**

I built ClinScribe, a clinical copilot that answers doctors' questions from guidelines and drug labels,
drafts SOAP notes from consultations, and never writes to the record without a doctor's approval. All
data is synthetic or public. The rule I held it to: every sentence cites a source passage, or the system
abstains.

Over two weeks I measured each retrieval upgrade against a 235-question golden set with paired bootstrap
confidence intervals, and kept only what beat the step before it:

- Hybrid search (dense + BM25 with RRF) alone: no gain at the top ranks.
- ColBERT reranking on top: recall@10 0.813 → 0.876. A cross-encoder: no gain, and ~3 s per query on CPU.
- Contextual retrieval (a local 3B model writing a short context prefix per chunk): MRR 0.607 → 0.680.
- Late chunking: worse (−0.048 recall@10); chunk vectors of long sections converged.
- Chosen pipeline vs dense-only: recall@10 0.809 → 0.909, +0.100 [95% CI +0.053, +0.148].

Then the surprise. On cited answers, faithfulness did not move: 0.937 for dense-only, 0.941 for the best
pipeline. What moved was correctness, 0.760 → 0.910, and wrong refusals, 18% → 2%. Because the
generator abstains rather than guesses, worse retrieval doesn't produce unfaithful answers, it produces
fewer answers. I had to change my own exit gate: "beats dense-only on faithfulness" was the wrong
question; "more correct, and no less faithful" was the right one.

Three other things I learned:

1. **A failover chain is only as good as the aliases tasks actually use.** An outage drill through the
   real API failed half the questions although failover "worked": answers were bound to a fallback
   alias that had no fallback of its own.
2. **Load tests find what unit tests can't.** De-identification ran in one process; it was fast alone
   (39 ms) and queued to 26 s at p95 under ten sessions. Three workers tripled throughput.
3. **Red-team suites need a negative control.** 63 of 63 adversarial cases passed; with the guardrails
   switched off, 23 of 63 did. Without that second number, 100% means nothing.

A 5-minute demo, from a recorded consultation to an approved FHIR note: https://youtu.be/Nu2pVtMFT-g

Everything is in the repo: evaluation reports, 29 ADRs, five postmortems, and a DPIA that lists what
is still missing before real use (because "designed for compliance" is not "compliant").
