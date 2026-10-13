# ClinScribe — clinical copilot with cited answers and human-approved writes

A portfolio project that applies real-time AI, agents, advanced RAG, LLMOps and healthcare
compliance end to end. **Synthetic and public data only**; designed for HIPAA, GDPR and the EU AI Act,
not certified.

- **Ask:** a clinician's question gets a cited answer from guidelines and drug labels; every sentence
  cites a source passage or the system abstains.
- **Scribe:** a consultation transcript becomes a SOAP draft; the doctor approves, edits or rejects,
  and only then is a FHIR `DocumentReference` written.
- **Lab:** a lab-report PDF becomes FHIR `Observation`s with abnormal values flagged; the doctor
  confirms before anything is saved.

## Architecture

```text
 React review UI ──> FastAPI (auth/RBAC, audit) ──> de-ID service (Presidio + rules + cues)
                                │
                                ▼
                    LangGraph agent graph: intake -> router -> fast | agentic (grade, rewrite,
                    drug facts) -> guardrails -> [doctor review interrupt] -> commit
                                │ MCP (streamable HTTP)
        ┌───────────────────────┼─────────────────────────────┐
  guidelines-mcp           druggraph-mcp                 fhir-mcp
  dense+BM25 RRF,          DDInter 2.0 in Neo4j          patient context (audited),
  ColBERT rerank,          (234,981 pairs)               approval-gated writes,
  contextual chunks                                     lab-report parsing
  (Qdrant)                                               (HAPI FHIR, Synthea)
                                │
                    LiteLLM gateway: Gemini Flash -> Groq -> OpenRouter :free -> local Ollama
                                │
        OpenTelemetry (redaction) -> local traces / Langfuse   ·   hash-chained audit log (Postgres)
```

Design rules: no PHI reaches a model, log or trace before de-identification; every model call goes
through one gateway; no clinical write without a doctor's approval token for the exact content.

## Results (all from `evals/reports/`, synthetic/public data, one laptop)

| Area | Result | Report |
|---|---|---|
| Retrieval | recall@10 0.809 (dense) → **0.909** (hybrid + ColBERT + contextual), +0.100 [95% CI +0.053, +0.148]; MRR@10 0.562 → 0.680; p50 159 / p95 206 ms per query on CPU | `rag/ablation.md` |
| Rejected by measurement | cross-encoder (no gain, ~3 s/query), late chunking (−0.048 recall@10), GraphRAG candidates (no gain) | `rag/ablation.md` |
| Cited answers | correctness 0.760 → **0.910** (+0.150 [+0.050, +0.260]); faithfulness 0.937 vs 0.941 (non-inferior); false abstentions 18% → 2% | `rag/answers_*` |
| Drug facts | interaction pairs no passage mentions: answered 10/10 with DDInter facts vs 4/10 without | `rag/answers_graph_facts.md` |
| Safety | red-team **63/63** (unsourced doses, diagnosis wording, injections, PHI, unapproved writes); negative control 23/63 | `redteam/redteam.md` |
| Privacy | 0 seeded PHI values in 6 sinks (traces, logs, Langfuse, spend logs, audit, mapping); de-ID structured recall 1.000, names 0.973, places 0.850 (held-out) | `privacy/` |
| Scribe | ACI-Bench: 6/8 drafts, 5 clean first time; long consultations exceed the free-tier output budget | `agents/note_writer.md` |
| Lab | 162/162 values mapped and flagged (fixed synthetic layout); wrong-patient control 20/20 | `lab/lab_parser.md` |
| Reliability | turns succeed with the primary down (p50 779 / p95 1,080 ms) and with **every cloud provider down** (local Ollama) | `llmops/`, `just gate 5` |
| Load | Ask endpoint, mocked model: p50 / p95 1.7 / 2.9 s at 10 sessions, 8.1 / 10.0 s at 50, 14.5 / 25.1 s at 100; 0 errors; ~5 req/s (de-ID was the bottleneck: 3 workers tripled throughput) | `load/load_test.md` |
| Cost | one consultation (draft + 3 questions) at list price: $0.050 (Gemini 3.5 Flash) … $0.002 (Groq gpt-oss-20b); free tiers bill $0 | `llmops/cost_per_consultation.md` |
| Incidents | 3 drills with postmortems: provider outage (found and fixed a fallback gap: 2/4 → 4/4 answered), retrieval drift, latency spike | `docs/postmortems/` |

Phase gates (`just gate N`) pass for phases 1, 3 and 5; phase 2 passes every criterion except the
human review of the golden-set sample (pending); phase 4 (voice) is not built; `just gate 6` lists the
SPEC §14 deliverables still pending (voice evidence, voice ADRs, demo video).

## Run it

Windows + Docker Desktop (WSL2), `uv`, `just`; details in `docs/runbooks/local-setup.md`.

```text
just gen-keys            # generated secrets into .env (add provider keys yourself)
just up; just up rag     # stack (core + FHIR + retrieval)
just fhir-load           # 50 Synthea patients
just token dr-demo       # bearer token for a synthetic demo doctor
npm --prefix apps/web install; npm --prefix apps/web run dev   # review UI on :5173
just test; just gate 3   # tests; a phase gate
```

## Limitations (honest notes)

- Synthetic and public data only; real clinical performance needs a proper study and a clinician-
  reviewed evaluation set (the golden-set review is pending).
- "Designed for compliance" is not "compliant": see `docs/compliance/` for the DPIA and the gaps
  (no erasure endpoint, free-tier processors without BAAs/DPAs, no TLS inside the stack).
- Voice (SPEC Phase 4) is not built yet: it needs speech-provider keys.
- The de-ID LoRA fine-tune is prepared (`finetune/`) but not trained (runs on Colab).
- Free-tier rate limits shaped the evaluations (60-question answer subset, 8 scribe dialogues).
- Lab parsing is measured on one synthetic layout; scanned reports (true OCR) are not covered.

## A note on JEPA

Joint-Embedding Predictive Architectures (LeCun et al.; I-JEPA, V-JEPA) learn by predicting the
*representation* of a masked part of the input rather than its pixels or tokens, which favours
abstract, predictive features over surface detail. ClinScribe does not use JEPA: it relies on
pretrained text encoders and LLMs. Where it could matter later: self-supervised representations of
clinical time series (vitals, labs) or audio, where predicting in embedding space avoids modelling
noise. This is a reading note, not a claim of experience.

## Docs

`docs/SPEC.md` (specification) · `docs/PROGRESS.md` (log of every task and number) · `docs/adr/`
(nine decision records) · `docs/compliance/` · `docs/runbooks/` · `docs/postmortems/` ·
`CONTRIBUTING.md`.
