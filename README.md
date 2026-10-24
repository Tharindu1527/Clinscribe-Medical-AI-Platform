# ClinScribe — clinical copilot with cited answers and human-approved writes

A portfolio project that applies real-time AI, agents, advanced RAG, LLMOps and healthcare
compliance end to end. **Synthetic and public data only**; designed for HIPAA, GDPR and the EU AI Act,
not certified.

- **Ask:** a clinician's question gets a cited answer from guidelines and drug labels; every sentence
  cites a source passage or the system abstains.
- **Scribe:** a consultation (live audio with the speakers told apart, or a transcript) becomes a
  SOAP draft; the doctor approves, edits or rejects,
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
Only the doctor's screen and the approved record see the originals, re-identified by the API and
audited (ADR-0015).

## Results (all from `evals/reports/`, synthetic/public data, one laptop)

| Area | Result | Report |
|---|---|---|
| Retrieval | recall@10 0.809 (dense) → **0.909** (hybrid + ColBERT + contextual), +0.100 [95% CI +0.053, +0.148]; MRR@10 0.562 → 0.680; p50 159 / p95 206 ms per query on CPU | `rag/ablation.md` |
| Rejected by measurement | cross-encoder (no gain, ~3 s/query), late chunking (−0.048 recall@10), GraphRAG candidates (no gain) | `rag/ablation.md` |
| Cited answers | correctness 0.760 → **0.910** (+0.150 [+0.050, +0.260]); faithfulness 0.937 vs 0.941 (non-inferior); false abstentions 18% → 2% | `rag/answers_*` |
| Drug facts | interaction pairs no passage mentions: answered 10/10 with DDInter facts vs 4/10 without | `rag/answers_graph_facts.md` |
| Safety | red-team **63/63** (unsourced doses, diagnosis wording, injections, PHI, unapproved writes); negative control 23/63 | `redteam/redteam.md` |
| Privacy | 0 seeded PHI values in 6 sinks (traces, logs, Langfuse, spend logs, audit, mapping); de-ID structured recall 1.000; names / places on unseen phrasings 0.973 / 0.850 with spaCy rules → **0.991 / 1.000 with the LoRA fine-tuned tagger** (held-out v1; 1.000 / 1.000 on a set frozen before training), PHI-free sentences altered 1/40 vs 3/40 (ADR-0014) | `privacy/` |
| Scribe | ACI-Bench: 6/8 drafts, 5 clean first time; long consultations exceed the free-tier output budget | `agents/note_writer.md` |
| Lab | 162/162 values mapped and flagged (fixed synthetic layout); wrong-patient control 20/20 | `lab/lab_parser.md` |
| Reliability | turns succeed with the primary down (p50 779 / p95 1,080 ms) and with **every cloud provider down** (local Ollama) | `llmops/`, `just gate 5` |
| Load | Ask endpoint, mocked model: p50 / p95 1.7 / 2.9 s at 10 sessions, 8.1 / 10.0 s at 50, 14.5 / 25.1 s at 100; 0 errors; ~5 req/s (de-ID was the bottleneck: 3 workers tripled throughput) | `load/load_test.md` |
| Cost | one consultation (draft + 3 questions) at list price: $0.050 (Gemini 3.5 Flash) … $0.002 (Groq gpt-oss-20b); free tiers bill $0 | `llmops/cost_per_consultation.md` |
| Voice | time to first audio p50 / p95 **4.3 / 7.1 s** with Deepgram Aura-2 speech (2026-10-19, 29/30 answered; 3.5 / 19.7 s with Cartesia on 2026-10-14, whose first byte was ~600 ms faster) vs SPEC budget 1.5 s: **not met**, bottleneck is the non-streamed cited answer; Gemini Live speech-to-speech 3.5 / 6.1 s, no citations or guardrails | `voice/latency.md`, ADR-0011, ADR-0013 |
| Speech recognition | PriMock57: WER 0.119 (nova-3) vs **0.112 (nova-3-medical)**; medical-term errors 18 → 12 of 200; keyterm boosting no gain | `voice/asr_wer.md` |
| Turn taking | 12 questions with a 0.7–2.0 s pause inside the sentence: cut off 27/36 (VAD only), 10/36 (semantic model), **1/36 (semantic, transcript punctuation off; adopted, ADR-0012)**, at the cost of a ~3 s end of turn on 4 of 12 whole questions; barge-in stops the agent's audio in p50 616 / p95 629 ms; self-interruption from echo 0/8 replies with echo cancellation, 8/8 without | `voice/turn_taking.md` |
| Scribe from audio | PriMock57, doctor + patient mixed to one live stream with diarization: **0.979** of words to the right speaker (role rule refined on this set; first rule 0.783), doctor found 6/6, WER 0.143; drafts 5/6 (the 108-turn visit exceeded the free-tier output budget) | `voice/scribe_diarization.md` |
| Incidents | 3 drills with postmortems: provider outage (found and fixed a fallback gap: 2/4 → 4/4 answered), retrieval drift, latency spike | `docs/postmortems/` |

Phase gates (`just gate N`) pass for phases 1, 3, 4 and 5; phase 2 passes every criterion except the
human review of the golden-set sample (pending). The demo video (4 min 50 s, recorded live by
`just demo-video`; what is live and what is not: `docs/presentation/demo_video.md`) goes from a spoken
question to a recorded consultation streamed into Scribe, through the doctor's review to an approved
FHIR note.

## Run it

Windows + Docker Desktop (WSL2), `uv`, `just`; details in `docs/runbooks/local-setup.md`.

```text
just gen-keys            # generated secrets into .env (add provider keys yourself)
just up; just up rag     # stack (core + FHIR + retrieval)
just fhir-load           # 50 Synthea patients
just token dr-demo       # bearer token for a synthetic demo doctor
just voice               # talk to ClinScribe (microphone + speakers; DEEPGRAM key)
just scribe 1617         # Scribe a consultation from the microphone (Enter to finish) or --file x.wav
npm --prefix apps/web install; npm --prefix apps/web run dev   # review UI on :5173
just demo-video          # re-record the demo video (needs the UI dev server, DEV_LOGIN=true, ffmpeg)
just test; just gate 3   # tests; a phase gate
```

## Limitations (honest notes)

- Synthetic and public data only; real clinical performance needs a proper study and a clinician-
  reviewed evaluation set (the golden-set review is pending).
- "Designed for compliance" is not "compliant": see `docs/compliance/` for the DPIA and the gaps
  (no erasure endpoint, free-tier processors without BAAs/DPAs, no TLS inside the stack).
- Voice: the cascaded agent works (`just voice`, console mode) but misses the latency budget; no
  browser/WebRTC client yet (needs a LiveKit server and a token endpoint).
- Scribe from audio: measured on two close-talk microphones mixed, not one room microphone; the
  role rule was refined on the evaluation set; live diarization did not separate two synthetic
  TTS voices; visits of 100+ turns are near the free-tier output budget (one of six failed).
- The de-ID tagger (LoRA, trained on Colab) was trained and tested on synthetic sentences only; it is
  opt-in (`DEID_NER=tagger`, ADR-0014) because the model is a local artefact, so CI and a fresh clone
  run the spaCy rules; it costs ~35 ms per de-ID call.
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
(twelve decision records) · `docs/compliance/` · `docs/runbooks/` · `docs/postmortems/` ·
`CONTRIBUTING.md`.
