# ClinScribe — Voice Clinical Copilot: Project Documentation

Oct 3, 2026 · @Y

## 1. Overview

ClinScribe is a voice-first clinical copilot. It turns a live doctor–patient consultation into an approved SOAP note stored as FHIR, and it answers the doctor's spoken questions with cited evidence. It is built as one complete portfolio project that applies every requirement of a Senior AI Engineer (clinical AI) role: real-time voice, agents, advanced RAG, LLMOps and healthcare compliance.

**Problem.** Physicians lose time to documentation, and AI decision support is only usable if every claim is traceable and a human stays in control.

**Design principles**

- Patient safety first: the AI drafts and suggests; the doctor approves every clinical write.
- Simple, measured pipeline: each added technique must beat a baseline in the evaluation report, or it is removed.
- No PHI reaches an LLM, a log or a trace before de-identification.
- Everything is observable: every turn is traced, timed and costed.

**Success criteria (targets, to be confirmed by measurement)**

| Area | Metric | Target |
| --- | --- | --- |
| Voice | Time to first audio (TTFA), p95 | < 1,500 ms (cascaded path) |
| Voice | End-to-end turn time, p95 | < 2,500 ms |
| Voice | Medical-term word error rate | Lower than vendor default after keyterm boosting |
| RAG | Faithfulness (RAGAS) | ≥ 0.90 |
| RAG | Citation precision | ≥ 0.95 |
| Safety | Unsourced dosage statements on red-team set | 0 |
| Safety | Clinical writes without doctor approval | 0 |
| Privacy | PHI found in exported traces (seeded test) | 0 |
| Reliability | Turns that survive a primary-provider outage | 100% via failover |

## 2. Scope and use cases

ClinScribe serves one primary user, the physician, through three modes. Each mode ends at a human checkpoint.

| Mode | Input | Output | Human checkpoint |
| --- | --- | --- | --- |
| Scribe | Live consultation audio (doctor + patient) | Structured SOAP note, coded as FHIR | Doctor approves or edits before save |
| Ask | Doctor's spoken question | Spoken + on-screen answer, every claim cited | Doctor decides; no automatic action |
| Lab | Lab report PDF | FHIR Observations, abnormal values flagged | Doctor confirms parsed values |

**Users**

- Physician: runs consultations, asks questions, approves notes.
- Clinic admin: manages users and roles, reads audit logs.
- AI engineer (operator): monitors traces, runs evaluations, handles incidents.

**User stories**

1. As a doctor, I talk with my patient normally and get a draft SOAP note when the visit ends.
2. As a doctor, I can interrupt the assistant mid-sentence and it stops at once.
3. As a doctor, I ask "any interaction between warfarin and the new antibiotic?" and hear an answer with sources I can open.
4. As a doctor, I see which statements in a draft have no source, before I approve.
5. As an admin, I can see who viewed or changed a record, when, and which model and prompt version produced it.
6. As an operator, I can trace one slow or wrong answer down to the exact retrieval, model call and latency step.

**Out of scope**

- Real patient data. All data is synthetic or public.
- Autonomous diagnosis or prescribing. The system suggests; it never decides.
- Certified HIPAA, GDPR or EU AI Act compliance. The system is *designed for* these rules, and the documents show how.
- Deployment in a real clinic, and mobile apps.

## 3. System architecture

ClinScribe is a layered system: voice in at the top, models at the bottom, and a PHI boundary in between that every LLM call must cross.

&#91;embedded content: ClinScribe system architecture · 7 layers + observability\]

Audio enters through WebRTC, becomes a transcript, and is de-identified before the agents see it. Agents call tools through MCP and reach every model through the LiteLLM gateway, while traces, audit records and evaluation scores flow to the observability column.

**Request flows**

1. Scribe: audio → diarized transcript → de-ID → note-writer agent → guardrail check → doctor review → FHIR DocumentReference + audit record.
2. Ask: question audio → transcript → de-ID → router → fast RAG or agentic loop → cited answer → citation check → TTS reply + on-screen sources.
3. Lab: PDF upload → OCR → lab-parser agent → FHIR Observations (pending) → doctor confirms → saved.

**Key design decisions**

| Decision | Choice | Why |
| --- | --- | --- |
| Default voice path | Cascaded | Text can be de-identified, guarded and audited |
| Orchestrator | LangGraph | Explicit state, human interrupts, replay |
| Tool integration | MCP servers | Standard, testable tool contracts |
| Model access | One gateway | Failover, budgets, single place for redaction |
| Clinical writes | Only after approval | Patient safety and EU AI Act oversight |

## 4. Voice AI layer

The voice layer runs two interchangeable pipelines behind one flag (`VOICE_MODE=cascaded|s2s`), so latency, quality and privacy can be compared on the same test set. Both run as LiveKit Agents workers; audio travels over WebRTC through a LiveKit server.

**Pipelines**

|  | Cascaded (default) | Speech-to-speech |
| --- | --- | --- |
| Chain | Deepgram streaming STT → LLM via gateway → Cartesia/ElevenLabs streaming TTS | Gemini Live (free tier); OpenAI Realtime is compared in an ADR only |
| Strength | Full control: text can be de-identified, guarded and audited at every step | Lowest latency, natural prosody |
| Weakness | More hops, more latency | Raw audio goes to the provider before de-ID; harder to guard |
| Clinical use | Default for Ask mode | Only with a BAA-covered provider; compared in an ADR |

**Scribe mode** is ambient: it listens and never speaks. It uses Deepgram streaming with speaker diarization (doctor vs patient) and sends the finished transcript to the note-writer agent.

**Turn detection.** Two strategies are built and compared:

- Server VAD (Silero): ends the turn after a fixed silence. Simple, but it cuts off doctors who pause to think.
- Semantic turn detection (LiveKit turn-detector model): judges from the words whether the speaker has finished.
- Measured: false cut-off rate, and the extra delay each strategy adds.

**Interruptions and echo**

- Barge-in: when the doctor speaks while the agent is talking, TTS stops, the LLM stream is cancelled, and the conversation history is cut to the words actually played. Each event is logged with its stop latency.
- Echo cancellation: browser WebRTC AEC, noise suppression and auto gain are on. A speaker-playback test measures how often the agent interrupts itself.

**Medical speech recognition**

- Keyterm boosting with drug names (RxNorm) and common clinical terms.
- Benchmark on PriMock57 consultation audio: overall WER and medical-term WER, Deepgram vs AssemblyAI, with and without boosting.
- Low-confidence drug names are highlighted for the doctor, never silently corrected.

**Latency instrumentation.** Every turn emits OpenTelemetry spans for each stage, so p50 and p95 can be reported per stage.

- Time to first audio (TTFA): from the end of the doctor's speech to the first agent audio frame.
- End-to-end turn time: from the end of the doctor's speech to the end of the agent's reply.
- Per-stage spans: turn detection, STT final, LLM time to first token, TTS first byte, network.

## 5. Agent layer

Agents run as one LangGraph state graph. Every tool has a typed contract, every output is validated, and every clinical write stops at a human-approval interrupt.

**Graph nodes**

1. `intake`: receives de-identified text and the mode (scribe, ask, lab).
2. `router`: sends simple lookups to fast RAG and multi-step questions to the agentic loop (section 6).
3. `note_writer`, `ask_agent`, `lab_parser`: the mode-specific agents.
4. `guardrail_check`: validates schema, citations and safety rules on the output.
5. `hitl_review`: a LangGraph `interrupt()`; the doctor approves, edits or rejects.
6. `commit`: writes FHIR resources and the audit record, only after approval.

**Tool contracts (exposed as MCP servers)**

| Tool | MCP server | Input | Output | Side effect |
| --- | --- | --- | --- | --- |
| `search_guidelines` | guidelines-mcp | query, filters | list of Evidence (chunk id, text, source URL, score) | None |
| `check_interactions` | druggraph-mcp | list of drug names | list of Interaction (pair, severity, source) | None |
| `get_patient_context` | fhir-mcp | patient id | minimal PatientSummary | Read logged in audit |
| `parse_lab_report` | fhir-mcp | file id | list of Observation | None until approved |
| `write_fhir` | fhir-mcp | FHIR resource | resource id | Write; requires approval token |

The A2A protocol is not needed for one system. An ADR explains where it would fit, for example handing a referral to another organisation's agent.

**Structured outputs.** All agent outputs are Pydantic models, enforced with the provider's structured-output mode and re-validated in code. The SOAP note is a list of statements per section; each statement carries its text, the transcript span it came from, and any citation ids.

**Guardrails**

- Input: block prompt-injection text found in retrieved documents or uploaded PDFs; confirm text is de-identified.
- Output: every clinical claim needs a citation; any dose statement needs a source; no definitive diagnosis wording; schema must validate.
- On failure: retry once with the error attached, then return a safe "cannot answer with evidence" reply.

**Human in the loop.** The review screen highlights statements without a source and low-confidence ASR words. Doctor edits are saved as before/after pairs, which become new evaluation data.

**Framework choice.** LangGraph is the orchestrator because it gives explicit state, interrupts and replay. Pydantic AI and the OpenAI Agents SDK are compared in an ADR on one task, so the choice is justified rather than assumed.

## 6. Advanced RAG pipeline

Retrieval runs on two paths chosen by a router, and no answer reaches the doctor until every clinical claim is tied to a source chunk.

&#91;embedded content: RAG pipeline · ingestion, two query paths, citation gate\]

Simple lookups take the fast path; multi-step questions take the agentic loop. A failed citation check sends the question back for another retrieval, or ends in an honest "no evidence found".

**Ingestion (offline)**

- Parse guideline articles, WHO documents and drug labels; keep section titles and source URLs as metadata.
- Contextual retrieval: an LLM writes a short prefix that places each chunk in its document, and the prefix is embedded with the chunk.
- Late chunking: a long-context embedding model encodes the whole document, then pools token vectors per chunk. Both methods are compared, not stacked by default.
- Indexes: Qdrant for dense vectors, a BM25 index for keywords, and Neo4j for drug and interaction relations.

**Fast path**

1. Hybrid search: dense and BM25 run in parallel, and their rankings are merged with reciprocal rank fusion (RRF).
2. Rerank: a cross-encoder rescores the merged candidates; ColBERT late-interaction reranking is tested as the alternative.
3. Generate: the model answers using only the top chunks and must cite a chunk id for each claim.

**Agentic path**

- Self-RAG style: the model decides whether more retrieval is needed and critiques its own draft.
- CRAG style: a grader scores each retrieved chunk; weak results trigger a rewritten query instead of a weak answer.
- GraphRAG: drug questions query the Neo4j graph for interaction paths, then fetch supporting text chunks.

**Citation grounding.** A separate check confirms that each cited chunk actually supports its sentence. Unsupported sentences are removed or flagged, and the doctor sees the source link next to every claim.

**Routing rule.** The router is a small, fast classifier prompt. It is judged by how often it picks the cheaper path without losing answer quality.

## 7. LLMOps and production

Every model call goes through one gateway and leaves one de-identified trace, so cost, latency and failures can be explained per turn.

**LLM gateway (LiteLLM proxy)**

- Fallback chain (free tiers only): Gemini Flash → Groq → OpenRouter `:free` models → local Ollama model (~3B quantized, on the host GPU, reached at `host.docker.internal`).
- Per-key rate limits and budgets; cost per request logged and summed per consultation.
- Model per task set in `config/models.yaml`, chosen from evaluation results (quality, p95 latency, cost), not by habit.
- Prompt caching: the static system prompt and tool definitions sit first in every prompt, and the saving is measured using Gemini's implicit caching.

**Tracing and telemetry**

- Langfuse Cloud (free tier; traces are de-identified and data is synthetic, see ADR-0002) holds traces, prompt versions and evaluation scores. Arize Phoenix is tried once and compared in an ADR.
- OpenTelemetry spans follow the GenAI semantic conventions, for example `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`.
- A redaction processor removes PHI from span attributes before export, as a second line of defence behind the de-ID service.
- Grafana dashboards: p50/p95 latency per stage, error rate, failover count, cost per consultation.

**Prompts and configs as code**

- Prompts live in `prompts/*.yaml` with a version, target model and parameters; agent graphs and guardrail rules are config files too.
- CI on every pull request: schema lint, prompt render tests, then the golden-set regression. The build fails if a quality metric drops below its threshold.
- The prompt version is written into every trace and audit record.

**Incident practice.** Three incidents are injected with chaos switches, then debugged from traces only, and written up as postmortems (timeline, impact, root cause, fix, prevention).

| Incident | Injected fault | Expected detection |
| --- | --- | --- |
| Provider outage | Primary API returns errors | Failover count rises; turns still succeed |
| Retrieval drift | Index rebuilt with a wrong chunking config | Faithfulness and citation precision drop in nightly eval |
| Latency spike | Delay added to TTS | p95 TTFA alert; trace shows the slow span |

**Deployment.** Docker Compose runs the full stack locally with one command. Runbooks cover start-up, key rotation, re-indexing and rollback of a prompt version.

## 8. Healthcare compliance and patient safety

The system is designed to meet HIPAA, GDPR and EU AI Act expectations, and each rule maps to a concrete control that can be demonstrated. It is not certified; that would need legal review.

**PHI de-identification service**

- Microsoft Presidio with custom recognisers (MRN, dates, phone numbers, addresses), plus a LoRA-fine-tuned NER model for names in clinical speech.
- Covers the 18 HIPAA Safe Harbor identifier types.
- PHI is replaced with consistent surrogates ("PATIENT\_1"). The mapping is encrypted and only used to re-identify text in the doctor's own screen.
- Placed before the LLM gateway, before logging and before trace export.
- Speech vendors receive raw audio, so they must be BAA-covered; a self-hosted Whisper option is documented as the alternative.

**Regulation to control map**

| Rule | Requirement | ClinScribe control | Evidence |
| --- | --- | --- | --- |
| HIPAA | Minimum necessary PHI; BAAs with vendors | De-ID service; `get_patient_context` returns a minimal summary | BAA vendor matrix document |
| GDPR | Health data is special category; DPIA; DPAs | Data minimisation, retention limits, erasure endpoint | DPIA and subprocessor list |
| EU AI Act | High-risk system: oversight, logging, transparency | HITL approval; automatic logs; AI-generated label on all drafts | AI Act checklist |
| Audit | Who did what, when, with which model | Append-only, hash-chained audit table | Audit log export |
| Access | Role-based access | RBAC: doctor, admin, operator | Access test suite |
| Identity | Right patient, right record | Two identifiers checked before any write | Wrong-patient test cases |

**Interoperability**

- FHIR R4 on a HAPI FHIR server: Patient, Encounter, DocumentReference (the note), Observation (labs), MedicationStatement, AllergyIntolerance.
- HL7 v2: one ORU^R01 lab message is converted into FHIR Observations to show legacy integration.

**Patient safety hazards and controls**

| Hazard | Control |
| --- | --- |
| Hallucinated drug fact | Citation required; abstain when evidence is missing |
| Misheard drug name | Keyterm boosting; low-confidence words highlighted |
| Wrong patient | Two-identifier check before write |
| Over-trust in the AI | Drafts labelled as AI-generated; doctor must approve |
| Prompt injection in a document | Input guardrail on retrieved and uploaded text |

## 9. Data sources

All data is synthetic or public; no real patient data is used. Check each licence before use and record it in `data/LICENSES.md`.

| Dataset | Used for |
| --- | --- |
| Synthea | Synthetic FHIR R4 patients, encounters, medications, lab values |
| PriMock57 | Mock primary-care consultation audio, for ASR and diarization tests |
| ACI-Bench | Doctor–patient dialogues with reference notes, for note-quality evaluation |
| PubMed Central Open Access subset | Guideline and review articles for the RAG corpus |
| WHO guidelines | Public clinical guidelines for the RAG corpus |
| openFDA drug labels | Drug information and interaction text |
| DDInter | Drug–drug interaction pairs for the Neo4j graph |
| RxNorm (prescribable subset) | Drug vocabulary for ASR keyterms and name matching |
| Generated lab PDFs | Rendered from Synthea observations, for OCR tests |
| Golden Q&A set | 200+ hand-written questions with verified answers and sources |

The golden set is the most valuable asset. Ask a doctor or senior medical student to review a sample of it, and record who reviewed what.

## 10. Tech stack and repository

Python 3.11+ with FastAPI on the backend, React on the frontend, and Docker Compose to run everything.

| Layer | Tools |
| --- | --- |
| Frontend | React, LiveKit client SDK (WebRTC), note review UI |
| Voice | LiveKit server + LiveKit Agents (Pipecat compared in an ADR), Silero VAD, LiveKit turn detector, Deepgram, AssemblyAI, Cartesia, ElevenLabs, Gemini Live (OpenAI Realtime: ADR only) |
| Agents | LangGraph, Pydantic, MCP Python SDK |
| Retrieval | Qdrant (pgvector compared), BM25 (rank-bm25 or Qdrant sparse vectors), cross-encoder reranker, ColBERT via RAGatouille, Neo4j |
| Models | Free-tier APIs (Gemini Flash, Groq, OpenRouter `:free`) via LiteLLM; local Ollama model as last fallback; de-ID NER model fine-tuned with LoRA (PEFT) on Colab/Kaggle |
| OCR | Docling or Tesseract for lab PDFs |
| Evaluation | RAGAS, DeepEval, pytest, custom harness |
| Observability | Langfuse, OpenTelemetry, Prometheus, Grafana |
| Privacy | Microsoft Presidio, custom NER |
| Health data | HAPI FHIR server, Synthea, HL7 v2 parser |
| Testing and CI | k6 or Locust, GitHub Actions |

```text
clinscribe/
├── apps/
│   ├── web/                 # React doctor UI
│   └── api/                 # FastAPI: auth, RBAC, audit, review endpoints
├── voice/
│   ├── agent_cascaded.py
│   ├── agent_s2s.py
│   └── turn_detection/
├── agents/
│   ├── graph.py             # LangGraph state graph
│   ├── schemas.py           # Pydantic contracts
│   └── guardrails/
├── mcp_servers/
│   ├── guidelines_mcp/
│   ├── druggraph_mcp/
│   └── fhir_mcp/
├── retrieval/
│   ├── ingest/              # contextual + late chunking
│   ├── hybrid.py            # dense + BM25 + RRF
│   ├── rerank.py
│   └── graph/               # Neo4j loaders + queries
├── privacy/deid/
├── llmops/
│   ├── gateway/             # LiteLLM config
│   └── telemetry/           # OTel setup, redaction processor
├── prompts/                 # versioned YAML prompts
├── config/                  # models.yaml, guardrails.yaml
├── finetune/                # LoRA training notebooks (Colab/Kaggle)
├── evals/
│   ├── golden/
│   ├── rag/  voice/  agents/  privacy/
│   └── reports/
├── load_tests/
├── docs/
│   ├── adr/  postmortems/  compliance/  runbooks/
├── .github/workflows/
└── docker-compose.yml
```

## 11. Evaluation and testing plan

Every claim in the final report is backed by a repeatable test in `evals/` and a number in `evals/reports/`. Latency is always reported as p50 and p95.

| Area | Metric | Method |
| --- | --- | --- |
| Voice latency | TTFA and end-to-end turn time, p50/p95 | OTel spans over 100+ scripted turns per pipeline |
| Turn taking | False cut-off rate; barge-in stop latency | Scripted audio with pauses and interruptions |
| Echo | Self-interruption rate | Speaker-playback test |
| ASR | Overall WER and medical-term WER | PriMock57, two vendors, boosting on/off |
| Retrieval | Recall@10, nDCG@10 | Golden set with labelled source chunks |
| Generation | Faithfulness, answer relevancy, context precision and recall | RAGAS |
| Citations | Citation precision and recall | Custom check: does the cited chunk support the sentence? |
| Agents | Tool-call accuracy; schema validity rate | DeepEval + pytest on recorded tasks |
| Safety | Guardrail catch rate | Red-team set (unsourced doses, diagnosis wording, injections) |
| Notes | Note quality vs reference | ACI-Bench; rubric-based LLM judge; doctor spot check |
| Privacy | PHI leak count in traces and logs | Seed transcripts with fake PHI, scan all exports |
| Load | p50/p95 latency and error rate at 10, 50, 100 sessions | k6 or Locust |
| Cost | Cost per consultation | Gateway cost logs |

**RAG ablation plan.** Each step is added alone and measured against the previous best:

1. Dense-only baseline
2. - BM25 with reciprocal rank fusion
3. - cross-encoder rerank, then ColBERT rerank (compare both)
4. - contextual retrieval chunks
5. - late chunking
6. - GraphRAG for drug questions
7. - adaptive routing (fast path vs agentic loop)

**Regression gates in CI.** A pull request fails when faithfulness, citation precision or schema validity fall below threshold, or when any PHI leak test fails. The nightly job runs the full golden set and the latency suite.

## 12. Implementation roadmap (~12 weeks, 6 gated phases)

The build takes about 12 weeks in six phases, and each phase ends with a measurable exit gate.

1. **Foundations (weeks 1–2):** HAPI FHIR + Synthea patients; PHI de-ID service; LiteLLM gateway with failover; Langfuse + OpenTelemetry with redaction; hash-chained audit table; CI with lint and tests.
   **Exit:** gateway answers when the primary provider fails; leak test finds 0 PHI in traces and logs; Synthea patients queryable from FHIR.
2. **Advanced RAG (weeks 3–5):** hybrid search + RRF, cross-encoder and ColBERT rerankers; contextual retrieval + late chunking; Neo4j drug graph; golden set + eval in CI.
   **Exit:** ablation report shows the chosen pipeline beats dense-only on recall@10 and faithfulness.
3. **Agents + safety (weeks 6–7):** LangGraph graph, MCP servers, structured outputs, guardrails, HITL review UI.
   **Exit:** red-team suite passes 100%; no FHIR write without approval (tested).
4. **Voice (weeks 8–9):** cascaded + speech-to-speech; turn detection, barge-in, AEC; medical WER benchmark.
   **Exit:** TTFA and turn-time p50/p95 reported; cascaded p95 within budget or the bottleneck explained from traces.
5. **Lab + open models (week 10):** lab PDF OCR → FHIR Observations; LoRA fine-tune of the de-ID NER model; local model as last gateway fallback.
   **Exit:** failover test completes a turn with all cloud providers disabled.
6. **Hardening (weeks 11–12):** load tests p50/p95; 3 injected incidents + postmortems; compliance docs; README; demo video.
   **Exit:** every item in section 14 is done.

Voice comes after retrieval and safety on purpose: a fast voice on top of an unmeasured core would only deliver wrong answers faster.

**Rule:** if a phase overruns, cut from phase 5 nice-to-haves, never from evaluation or safety.

## 13. Job requirement coverage

Every item in the job description maps to a feature and to evidence a reviewer can open.

| JD requirement | ClinScribe feature | Evidence |
| --- | --- | --- |
| Speech-to-speech + cascaded pipelines | Two voice pipelines behind a flag | Latency and quality comparison report |
| LiveKit Agents / Pipecat | LiveKit Agents workers; Pipecat trial | ADR-voice-framework |
| Server VAD vs semantic turn detection | Both built and measured | False cut-off results |
| Barge-in, echo cancellation | Interrupt handling; WebRTC AEC | Stop-latency and self-interruption tests |
| Medical ASR accuracy | Keyterm boosting; vendor benchmark | Medical-term WER table |
| TTFA and turn-time measurement | OTel spans per stage | p50/p95 latency report |
| Agent orchestration | LangGraph state graph | `agents/graph.py` |
| Tool contracts, structured outputs | Pydantic schemas for all tools and outputs | `agents/schemas.py` |
| Guardrails, human in the loop | Guardrail node; approval interrupt | Red-team results; review UI demo |
| MCP, A2A awareness | Three MCP servers; A2A ADR | `mcp_servers/`; ADR |
| Hybrid search + RRF | Dense + BM25 fusion | Ablation step 2 |
| Cross-encoder + ColBERT rerank | Both rerankers | Ablation step 3 |
| Contextual retrieval, late chunking | Two ingestion variants | Ablation steps 4–5 |
| Self-RAG, CRAG, adaptive routing | Router + agentic loop with grading | Ablation step 7 |
| GraphRAG + Neo4j | Drug interaction graph | Ablation step 6 |
| Citation grounding | Claim → chunk links; citation check | Citation precision and recall |
| RAGAS / DeepEval, golden set, prompt regression | Eval suite in CI | CI runs; `evals/reports/` |
| Frontier APIs, caching, model selection | Gateway routing; `models.yaml` | Cost, latency, quality table |
| Langfuse / Phoenix + PII redaction | Langfuse Cloud (free tier); redaction processor | PHI leak test |
| OpenTelemetry GenAI conventions | GenAI span attributes | Trace screenshots |
| LLM gateway | LiteLLM with failover and budgets | Provider outage postmortem |
| Prompts and configs under CI | Versioned YAML + CI checks | GitHub Actions history |
| Vector stores | Qdrant; pgvector comparison | ADR-vector-store |
| Latency, load, quality tests (p50/p95) | k6/Locust + eval suite | Load test report |
| Production incident debugging | Three injected incidents | Three postmortems |
| HIPAA, PHI de-ID, BAA | De-ID service; vendor matrix | Compliance docs |
| GDPR, DPIA, DPA | Minimisation, retention, erasure | DPIA document |
| EU AI Act high-risk | Oversight, logging, transparency | AI Act checklist |
| Audit trail, access control, patient identity | Hash-chained audit; RBAC; two-identifier check | Test suites |
| FHIR R4, HL7 | HAPI FHIR; ORU^R01 conversion | Integration tests |
| Mentoring, architecture | ADRs; contributor guide | `docs/adr/` |
| Nice to have: LoRA fine-tuning | De-ID NER model fine-tuned with LoRA | Training notebook + eval |
| Nice to have: vLLM / Ollama | Ollama serves a local model as the last gateway fallback (vLLM not run: 4 GB VRAM) | Failover test |
| Nice to have: medical OCR | Lab mode | OCR accuracy table |
| Nice to have: JEPA awareness | Research note only | README section |

## 14. Deliverables and definition of done

The project counts as complete only when every box below is ticked.

**Product**

- [ ] `docker compose up` starts the full stack on a clean machine
- [ ] Scribe, Ask and Lab modes work end to end on synthetic patients
- [ ] Doctor review UI with approve, edit and reject

**Evidence**

- [ ] Evaluation report: RAG ablations, ASR WER, agent and safety results
- [ ] Latency and load report with p50/p95 per stage and per concurrency level
- [ ] Cost per consultation, by model choice
- [ ] CI pipeline with passing eval gates, visible in GitHub Actions

**Documentation**

- [ ] Architecture overview and at least 6 ADRs (voice framework, S2S vs cascaded, vector store, orchestrator, reranker, A2A)
- [ ] Three incident postmortems
- [ ] Compliance pack: DPIA, BAA vendor matrix, EU AI Act checklist, audit design
- [ ] Runbooks and a contributor guide

**Presentation**

- [ ] 3–5 minute demo video of a live voice consultation through to an approved FHIR note
- [ ] README with results table, limitations and a short JEPA research note
- [ ] One blog post or LinkedIn write-up on the most interesting finding

## 15. Risks and limitations

The biggest risk is scope: this is a large build for one person, so each phase ships a working, measured slice before the next one starts.

| Risk | Mitigation |
| --- | --- |
| Scope too large for 12 weeks | Phase gates; cut nice-to-haves before core evaluation |
| API costs | Free tiers, small test sets for daily runs, prompt caching, full runs nightly only |
| Speech-to-speech path sends raw audio to the provider | Used only on synthetic data; documented as needing a BAA in real use |
| No clinician to validate answers | Golden set built only from cited guideline text; seek one reviewer for a sample |
| Dataset licence limits | Licences recorded per dataset; restricted data never committed to the repo |
| Vendor APIs change | All provider calls go through the gateway and plugin layer |

**Honest notes for interviews**

- JEPA is a research direction, not something this system uses; the README covers it as a short reading note.
- "Designed for compliance" is not "compliant"; say so plainly.
- Results come from synthetic and public data, and real clinical performance would need a proper study.
