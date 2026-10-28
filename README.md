# ClinScribe — clinical copilot with cited answers and human-approved writes

A portfolio project that applies real-time AI, agents, advanced RAG, LLMOps and healthcare
compliance end to end. **Synthetic and public data only**; designed for HIPAA, GDPR and the EU AI Act,
not certified.

- **Ask:** a clinician's question gets a cited answer from guidelines and drug labels; every sentence
  cites a source passage or the system abstains.
- **Scribe:** a consultation (live audio with the speakers told apart, or a transcript) becomes a
  SOAP draft; the doctor approves, edits or rejects,
  and only then is a FHIR `DocumentReference` written.
- **Lab:** a lab-report PDF or an HL7 v2 ORU^R01 message becomes FHIR `Observation`s with
  abnormal values flagged; the doctor confirms before anything is saved.

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
        span metrics -> Prometheus + gateway spend log -> Grafana (p50/p95 per stage, failovers, cost)
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
| Cited answers | correctness 0.760 → **0.910** (+0.150 [+0.050, +0.260]); faithfulness 0.937 vs 0.941 (non-inferior); false abstentions 18% → 2%; citation precision 0.926 → 0.875 vs SPEC target 0.95: **not met** (mostly "partial" links on sentences citing two sources); a local NLI runtime check was measured and rejected (ADR-0017) | `rag/answers_*`, `rag/citation_support.md` |
| Drug facts | interaction pairs no passage mentions: answered 10/10 with DDInter facts vs 4/10 without | `rag/answers_graph_facts.md` |
| Routing | 39 golden questions down both paths: the agentic loop raises faithfulness **+0.103** [+0.015, +0.206] but not correctness (0.833 both); the router (17% agentic on the full set) shows no measurable loss against always-agentic (correctness +0.026 [−0.026, +0.090], faithfulness −0.038 [−0.117, +0.019]) at ~1.3 vs 2.4 model calls per question; agentic median 7.2 s vs 1.9 s | `agents/router_quality.md` |
| Safety | red-team **67/67** (unsourced doses, also written in words, diagnosis wording, injections, PHI, unapproved writes, wrong-drug answers); negative control 23/67. Questions about a drug no source names abstain before any model call (0 of 209 answerable golden questions blocked, ADR-0018) | `redteam/redteam.md`, `rag/drug_grounding.md` |
| Privacy | 0 seeded PHI values in 6 sinks (traces, logs, Langfuse, spend logs, audit, mapping); de-ID structured recall 1.000; names / places on unseen phrasings 0.973 / 0.850 with spaCy rules → **0.991 / 1.000 with the LoRA fine-tuned tagger** (held-out v1; 1.000 / 1.000 on a set frozen before training), PHI-free sentences altered 1/40 vs 3/40 (ADR-0014) | `privacy/` |
| Scribe | ACI-Bench, 8 consultations vs the clinician's reference note (rubric judge, indicative): fact recall 0.85, **critical facts 0.92** (medications, doses, results, plan; controls: the reference 1.00, the draft without assessment and plan 0.50), statements supported by their cited turns 0.97 (3 of 171 not); all 8 drafted this time (6 of 8 on 2026-10-14: long consultations are near the free-tier output budget) | `agents/note_quality.md`, `agents/note_writer.md` |
| Lab | PDF: 155/155 values mapped and flagged (fixed synthetic layout); HL7 v2 ORU^R01: 155/155 (LOINC, value, UCUM unit, flag), identity checked by name, birth date and MRN; wrong-patient control 20/20 for both (ADR-0021) | `lab/lab_parser.md`, `lab/hl7_oru.md` |
| Reliability | turns succeed with the primary down (p50 779 / p95 1,080 ms) and with **every cloud provider down** (local Ollama) | `llmops/`, `just gate 5` |
| Load | Ask endpoint, mocked model: p50 / p95 1.7 / 2.9 s at 10 sessions, 8.1 / 10.0 s at 50, 14.5 / 25.1 s at 100; 0 errors; ~5 req/s (de-ID was the bottleneck: 3 workers tripled throughput) | `load/load_test.md` |
| Cost | one consultation (draft + 3 questions) at list price: $0.050 (Gemini 3.5 Flash) … $0.002 (Groq gpt-oss-20b); free tiers bill $0. Gemini implicit prompt caching saved nothing here: 0 cached tokens in 274 calls, including a controlled repeat test | `llmops/cost_per_consultation.md`, `llmops/prompt_cache.md` |
| Voice | time to first audio p50 / p95 **4.3 / 7.1 s** with Deepgram Aura-2 speech (2026-10-19, 29/30 answered; 3.5 / 19.7 s with Cartesia on 2026-10-14, whose first byte was ~600 ms faster) vs SPEC budget 1.5 s: **not met**, bottleneck is the non-streamed cited answer (a lower reasoning effort cut its output 282 → 98 tokens and the call's median by 0.7 s, paired over 10, but failed its quality rule, ADR-0025); Gemini Live speech-to-speech 3.5 / 6.1 s, no citations or guardrails. Over WebRTC through the self-hosted LiveKit server, measured at the client: 6.7 / 7.9 s (10 questions, 10 cited; audited as the doctor in the room, ADR-0019) | `voice/latency.md`, `voice/webrtc.md`, ADR-0011, ADR-0013 |
| Speech recognition | PriMock57: WER 0.119 (nova-3) vs **0.112 (nova-3-medical)**; medical-term errors 18 → 12 of 200; keyterm boosting no gain | `voice/asr_wer.md` |
| Turn taking | 12 questions with a 0.7–2.0 s pause inside the sentence: cut off 27/36 (VAD only), 10/36 (semantic model), **1/36 (semantic, transcript punctuation off; adopted, ADR-0012)**, at the cost of a ~3 s end of turn on 4 of 12 whole questions; barge-in stops the agent's audio in p50 616 / p95 629 ms; self-interruption from echo 0/8 replies with echo cancellation, 8/8 without | `voice/turn_taking.md` |
| Scribe from audio | PriMock57, doctor + patient mixed to one live stream with diarization: **0.979** of words to the right speaker (role rule refined on this set; first rule 0.783), doctor found 6/6, WER 0.143; drafts 5/6 (the 108-turn visit exceeded the free-tier output budget) | `voice/scribe_diarization.md` |
| CI gates | every pull request: lint, types, unit tests, the retrieval regression on a fixture index, the red-team suite and its control, the de-ID recall gates, prompt contracts and the prompt lock (a version names one text), and the committed answer evaluation checked against the current prompts, model and floors: a prompt or model change fails until its evaluation is committed (ADR-0026) | `config/quality_gates.yaml`, `prompts/versions.lock` |
| Incidents | 3 drills with postmortems: provider outage (found and fixed a fallback gap: 2/4 → 4/4 answered), retrieval drift, latency spike; plus one real defect: FastAPI's built-in telemetry had silently replaced the app-level span redaction (the collector's layer held: 0 leaks), now off and fail-closed | `docs/postmortems/` |

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
just up voice; just voice dev   # browser voice: LiveKit server + agent worker, then the Voice tab
just scribe 1617         # Scribe a consultation from the microphone (Enter to finish) or --file x.wav
just up obs; just migrate   # dashboards: Grafana on 127.0.0.1:3000 (admin / GRAFANA_ADMIN_PASSWORD)
just phoenix on         # optional local trace UI (Arize Phoenix, 127.0.0.1:6006); `just phoenix off`
npm --prefix apps/web install; npm --prefix apps/web run dev   # review UI on :5173
just demo-video          # re-record the demo video (needs the UI dev server, DEV_LOGIN=true, ffmpeg)
just test; just gate 3   # tests; a phase gate
```

## Limitations (honest notes)

- Synthetic and public data only; real clinical performance needs a proper study and a clinician-
  reviewed evaluation set (the golden-set review is pending).
- "Designed for compliance" is not "compliant": see `docs/compliance/` for the DPIA and the gaps
  (erasure and retention are operator commands, not an API endpoint; free-tier processors
  without BAAs/DPAs; no TLS inside the stack).
- Voice: the cascaded agent works in console mode and in the browser over WebRTC (`just up voice`,
  `just voice dev`, the Voice tab) but misses the latency budget; the WebRTC set-up is for one
  machine (127.0.0.1, no TURN, no TLS; ADR-0019).
- Scribe from audio: measured on two close-talk microphones mixed, not one room microphone; the
  role rule was refined on the evaluation set; live diarization did not separate two synthetic
  TTS voices; visits of 100+ turns are near the free-tier output budget (one of six failed).
- The de-ID tagger (LoRA, trained on Colab) was trained and tested on synthetic sentences only; it is
  opt-in (`DEID_NER=tagger`, ADR-0014) because the model is a local artefact, so CI and a fresh clone
  run the spaCy rules; it costs ~35 ms per de-ID call.
- Free-tier rate limits shaped the evaluations (60-question answer subset, 8 scribe dialogues).
- Lab parsing is measured on one synthetic layout; scanned reports (true OCR) are not covered.
  HL7 v2 messages come from one synthetic sender written by this project: no MLLP listener,
  no ACKs, no local codes or Z-segments.
- Evaluation tooling differs from SPEC §10–11 in one place: DeepEval is not used. The agent's tool
  calls are fixed code paths (no model chooses a tool), so "tool-call accuracy" reduces to the
  router's choice, measured in `agents/router.md` and `agents/router_quality.md`; generation is
  checked with our own judges, with
  RAGAS as a cross-check (`rag/ragas_calibration.md`).

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
