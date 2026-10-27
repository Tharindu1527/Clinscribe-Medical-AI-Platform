# ClinScribe — Progress

Last updated: 2026-10-26 · **Phase 1 — Foundations: COMPLETE (2026-10-06)**; de-ID v1 merged (PR #1).
**Phase 2 — Advanced RAG: gate passes except the golden review (task 3)**.
**Phase 3 — Agents + safety: COMPLETE (2026-10-14, `just gate 3` PASS)**.
**Phase 4 — Voice: COMPLETE (2026-10-14, `just gate 4` PASS; latency budget not met, bottleneck explained)**.
**Phase 5 — Lab + open models: COMPLETE (2026-10-14, `just gate 5` PASS)**; LoRA de-ID tagger trained
(round 2) and adopted behind `DEID_NER=tagger` (2026-10-24, ADR-0014).
**Phase 6 — Hardening: done; demo video re-recorded 2026-10-19 (upload pending)**.
Phases in total: 6 (SPEC §12).

## Agreed decisions (2026-10-04)

- Phase plan: SPEC section 12 (6 gated phases). Phase 1 adds the audit table and CI.
- Hardware budget: 16 GB RAM, WSL2 capped at 10 GB, RTX 3050 Laptop (4 GB VRAM).
  Docker Compose profiles; `just up` starts only the core stack (target ≤ 8 GB).
- Providers: free tiers only. Gateway fallback order: Gemini Flash → Groq → OpenRouter `:free` →
  Ollama on Windows (~3B quantized, GPU) at `host.docker.internal`. No vLLM.
  Speech-to-speech: Gemini Live; OpenAI Realtime in an ADR only. Caching measured on Gemini implicit caching.
- Tracing: Langfuse Cloud free tier instead of self-hosted Langfuse v3 (ADR-0002).
- Gateway scope: text generation + hosted embeddings through LiteLLM; local encoders in-process on
  de-identified text; RAGAS/DeepEval pointed at the gateway (ADR-0001).
- LoRA fine-tuning runs on Colab/Kaggle, not locally.
- One uv project with top-level packages; git-ignored `data/`; one Postgres with separate databases;
  auth/RBAC after the review UI exists (Phase 3).
- Default branch: `main`.

## Phase 1 — Foundations (weeks 1–2)

**Phase exit gate (SPEC §12):** (a) gateway answers when the primary provider fails;
(b) leak test finds 0 PHI in traces and logs; (c) Synthea patients are queryable from FHIR.
Run with `just gate 1`.

| # | Task | Exit-gate test | Status |
|---|------|----------------|--------|
| 0 | **Prerequisites (you):** install Docker Desktop (WSL2, `.wslconfig` memory=10GB), `just`, Ollama **installed to D:** (`OllamaSetup.exe /DIR=D:\Ollama`) + one ~3B quantized model; `uv self update`; `uv python install 3.11`. | `docker info`, `just --version`, `ollama list` (model present) and `uv python find 3.11` all succeed. | ✅ 2026-10-06 (Ollama 0.35.1 + `llama3.2:3b`; WSL cap temporarily 6 GB, see Blockers) |
| 1 | **Repo skeleton and tooling:** `pyproject.toml` (Python 3.11, ruff, mypy, pytest markers `unit`/`integration`/`live`), package folders, `justfile` (PowerShell shell), `.env.example`, `.gitignore`, `data/LICENSES.md`, `config/settings.py` (pydantic-settings, `SecretStr`), ruff banned-import rule for provider SDKs outside `llmops/gateway`. | On a clean clone, `uv sync; just lint; just test` pass. Tests: every Settings field has a key in `.env.example` and vice versa; `repr(Settings())` contains no secret value; a fixture that imports `openai` outside the gateway makes `ruff check` fail. | ✅ 2026-10-04 |
| 2 | **ADRs:** 0001 gateway scope, 0002 Langfuse Cloud vs self-hosted, 0003 Compose profiles and memory budget. | `tests/unit/test_adr_format.py`: every ADR has Context, Options, Decision, Consequences headings. You review and approve the text. | ✅ test passes; ADRs 0001–0004 approved by you 2026-10-06 |
| 3 | **Core Compose stack:** postgres (init script creates `clinscribe`, `litellm`, `hapi` databases and least-privilege roles), otel-collector, litellm, deid, api (one Python image), hapi-fhir (profile `fhir`); memory limits and healthchecks on every service. | `just up` → `tests/integration/test_stack_health.py`: all services healthy within 5 min. `just stats` total recorded below; target ≤ 8 GB. | ✅ 2026-10-05: 9/9 stack tests pass; 1.94 GB measured |
| 4 | **HAPI FHIR + Synthea:** pinned Synthea release (SHA-256 checked), seed 42, 50 patients, loaded in dependency order by `just fhir-load`; idempotent. | Integration tests: Patient count == 50; every patient has ≥ 1 Encounter; search by family name works; a second `just fhir-load` leaves the count at 50. | ✅ 2026-10-05: 4/4 pass (gate c) |
| 5 | **LiteLLM gateway with failover:** alias with the 4-step fallback chain, per-key budget and rpm, spend logs without prompt text, `config/models.yaml` (task → alias), `llmops/gateway/client.py` (accepts only `DeidentifiedText`), record/replay cache for tests, chaos switch `just chaos primary-down`. | Unit: client rejects a plain `str`; a replay-cache hit makes zero network calls. Live (`just test-live`): with the primary down, a request succeeds, the response names the Groq model, and the failover appears in spend logs. Ollama step is skipped if Ollama is not running. | ✅ 2026-10-05: live 2 pass, Ollama step skipped (model downloading) (gate a) |
| 6 | **De-ID service v0:** Presidio + spaCy `en_core_web_lg` + custom recognisers for the 18 Safe Harbor types; consistent surrogates per encounter (`PATIENT_1`); Fernet-encrypted mapping in Postgres; FastAPI `/deidentify` (and internal-only `/reidentify`). Seeded fake-PHI corpus generated with Faker. | `just eval privacy` writes `evals/reports/privacy/deid_v0.md` with recall per entity type. Structured types (MRN, phone, email, SSN, dates, ZIP, URL, IP, IDs) recall = 1.0; name recall recorded as the Phase 5 baseline. Same input → same surrogates. Raw DB row contains no plaintext. | ✅ 2026-10-05: 15/15 structured types recall 1.000; PERSON 0.95, LOCATION 0.75 (baseline) |
| 7 | **Telemetry with redaction:** OTel setup in `llmops/telemetry` with GenAI semantic-convention attributes; redacting exporter wrapper + logging redaction filter; collector redaction processor → Langfuse Cloud (EU) + local file exporter; LiteLLM OTel callback → collector. | Unit: a span and a log record carrying seeded PHI are exported without it. Integration: one request → one Langfuse trace (fetched via API) with api → deid → gateway spans and `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`. | ✅ 2026-10-05: unit 4/4, integration 2/2 (local export + Langfuse, no PHI); the api → deid → gateway chain check moves to task 9 (needs the endpoint) |
| 8 | **Audit table:** append-only, hash-chained (HMAC-SHA-256 with `AUDIT_CHAIN_KEY`); DB trigger blocks UPDATE/DELETE; app role has INSERT/SELECT only; advisory lock keeps order; `just audit-verify`. | Tests: chain verifies after 100 appends including 10 concurrent; UPDATE and DELETE as the app role raise; a manual tamper (as owner) is reported at the exact row. | ✅ 2026-10-05: 8/8 pass; `just audit-verify` OK |
| 9 | **Pipeline endpoint:** FastAPI `/health` and `POST /v1/dev/complete` (text → deid → gateway → answer), writing an audit record (actor, model, prompt version, trace id). | Integration: the endpoint returns an answer; an audit row exists with the same trace id as the Langfuse trace. | ✅ 2026-10-05: live 1/1 (answer, audit row = trace id, Langfuse trace has api + deid + gateway spans, no seeded PHI) |
| 10 | **PHI leak test (gate b):** `evals/privacy/leak_test.py` seeds 20 transcripts with fake PHI, sends them through the endpoint, then scans the collector file export, `docker compose logs` for every service, Langfuse traces for the run, LiteLLM spend logs and the audit table. | 0 leaks. Positive control: the scanner finds 100% of seed values in a planted file. Report in `evals/reports/privacy/`. | ✅ 2026-10-05: 0 leaks in 6 sinks (66 seed values), control 100% (gate b) |
| 11 | **CI** (after you add the GitHub remote): `.github/workflows/ci.yml` runs ruff, mypy and unit tests on every PR (replay cache, no secrets); integration job (core + fhir) on push to `main` and manual dispatch. | A PR shows green; a throwaway PR with a failing test goes red. You enable branch protection on `main` requiring CI. | ✅ 2026-10-06: green on `a8d0733` (lint-unit + integration); throwaway PR with a failing test went red; ruleset `protect-main` requires `lint-unit` |
| 12 | **Phase 1 exit:** `just gate 1`; `docs/runbooks/local-setup.md`; failover latency p50/p95 (20 calls, normal vs primary down); measured memory per service. | On a fresh clone, following the runbook: `just up; just fhir-load; just gate 1` passes. PROGRESS updated with the numbers. | ✅ 2026-10-06: fresh clone from GitHub at `9e300cb`, `just gate 1` 7/7 PASS |

### Phase 1 exit numbers (2026-10-06, fresh clone at `9e300cb`, after `just gate 1`)

| Container | Used | Limit |
|---|---|---|
| hapi-fhir | 1194 MB | 2048 MB |
| litellm | 564 MB | 1024 MB |
| deid (spaCy `en_core_web_md`) | 378 MB | 1536 MB |
| api | 136 MB | 512 MB |
| postgres | 108 MB | 512 MB |
| otel-collector | 56 MB | 256 MB |
| **total (core + fhir)** | **2.38 GB** | target ≤ 8 GB |

Gateway latency (`just eval latency`, `evals/reports/llmops/failover_latency.md`), 20 calls per mode, all succeeded:

| Mode | p50 | p95 | Served by |
|---|---|---|---|
| Primary up | 2,564 ms | 3,821 ms | Gemini Flash pool ×19, Groq ×1 |
| Primary down (chaos) | 779 ms | 1,080 ms | Groq `gpt-oss-20b` ×20 |

PHI leak test (gate b), run `bd445eaf`: 0 leaks in all 6 sinks, positive control 100%.
Lowest C: free space during the whole run: 2.35 GB.

### Memory budget (estimates per profile)

| Profile | Services | Est. RAM |
|---|---|---|
| core | postgres, otel-collector, litellm, deid, api | ~3.0 GB |
| fhir | hapi-fhir (JVM heap capped at 1.25 GB) | ~2.0 GB |
| `just up` (core + fhir, Phase 1) | | **~5.0 GB** |
| rag (Phase 2–3) | qdrant, neo4j (heap 768 MB + page cache 512 MB), guidelines-mcp (encoders, 0.62 GB measured) | ~3.5 GB |
| voice (Phase 4) | livekit-server, voice-agent, web | ~1.7 GB |
| obs (optional) | prometheus, grafana (ADR-0023) | 0.2 GB measured (62 + 137 MiB after use) |
| tools (one-shot) | synthea generator | ~1.0 GB while running |
| Ollama (Windows host, outside WSL cap) | ~3B Q4 model | ~2.5 GB VRAM + ~1 GB RAM |

## Phase 2 — Advanced RAG (weeks 3–5)

**Phase exit gate (SPEC §12, wording changed 2026-10-13):** the ablation report shows the chosen pipeline
beats dense-only on **recall@10** and **answer correctness**, with **faithfulness not worse by more than
0.05** (paired bootstrap 95% CI for each difference). Run with `just gate 2`.

**Decisions (you, 2026-10-06):** corpus = focused primary care (hypertension, type 2 diabetes, atrial
fibrillation/anticoagulation, asthma/COPD, common infections; ~200–400 docs, ~5–10k chunks); golden set
drafted by Claude from source passages (answers quoted, gold chunk ids), 20% sample reviewed by a human and
recorded; faithfulness on a stratified 60-question subset (dense-only vs best two), judge Groq
`gpt-oss-120b` via the gateway, cached.

**Defaults (from the plan):** local encoders on CPU first (measure; GPU only if too slow) —
`jina-embeddings-v2-base-en` (8k context, for dense and late chunking), `ms-marco-MiniLM-L-6-v2`
cross-encoder, ColBERT via **PyLate** (SPEC names RAGatouille, unmaintained since 2025-05); BM25 with
`rank-bm25` in-process; own RRF; contextual-retrieval prefixes from local Ollama through the gateway (no
free-tier quota). Corpus text is public (no PHI); patient-derived queries are de-identified before retrieval
(ADR-0001). Ablation step 7 (adaptive routing) and Self-RAG/CRAG move to Phase 3 (need the agent loop).

| # | Task | Exit-gate test | Status |
|---|------|----------------|--------|
| 0 | Licences for WHO guidelines, PMC OA (CC-BY/CC0 only), openFDA labels, DDInter in `data/LICENSES.md` | Every source has a licence and a verified date | ✅ 2026-10-06 |
| 1 | Corpus ingestion: fetch, parse, keep section titles and source URLs (`just ingest`) | Doc count; every chunk has URL + section; no duplicates; idempotent | ✅ 2026-10-06: 235 docs, 8,104 chunks; 6/6 corpus tests incl. byte-identical offline rebuild |
| 2 | `rag` Compose profile (Qdrant v1.19.2, Neo4j 5.26 LTS) with memory limits; dense baseline index | Health tests; whole stack ≤ 8 GB measured | ✅ 2026-10-06: 5/5 rag tests; 8,104 points; stack 3.59 GB |
| 3 | Golden set v1 (200+): question, quoted answer, gold chunk ids, category; ≥ 10% unanswerable | Validator: gold chunks exist and contain the answer; reviewed sample recorded | ◐ 2026-10-06: 235 items valid; **review sheet waiting for you** |
| 4 | Retrieval harness: recall@10, nDCG@10, MRR (`just eval rag`) | Baseline report; metric unit tests on hand-worked cases | ✅ 2026-10-06: dense recall@10 0.809, nDCG@10 0.583 |
| 5 | BM25 + RRF (ablation step 2) | RRF unit tests; step 2 vs baseline with CI | ✅ 2026-10-06: measured; hybrid not better at top 10 (CI spans 0) |
| 6 | Cross-encoder and ColBERT rerankers (step 3); ADR on the reranker | Both measured; ADR chooses with numbers | ✅ 2026-10-06: hybrid + ColBERT recall@10 0.876; ADR-0006 proposed |
| 7 | Contextual retrieval with local-LLM prefixes (step 4) | Prefixes cached; step 4 vs best so far | ✅ 2026-10-06: hybrid + ColBERT + context recall@10 0.909, MRR 0.680 |
| 8 | Late chunking (step 5), compared with contextual, not stacked | Step 5 vs best so far | ✅ 2026-10-07: measured; worse (dense recall@10 0.727 vs 0.809), rejected |
| 9 | Neo4j drug graph (DDInter + RxNorm) and GraphRAG for drug questions (step 6) | Graph counts; interaction-question subset vs best | ✅ 2026-10-08: 1,971 drugs, 234,981 interactions; no retrieval gain (17/19 already found), facts kept for task 10 |
| 10 | Generation with chunk-id citations, citation check, faithfulness (RAGAS via the gateway) | Faithfulness and citation precision: baseline vs best two | ✅ 2026-10-10: dense vs best two, 60 questions each: correctness better for both (+0.150 and +0.100, CIs exclude 0), faithfulness and citation precision not different (all ~0.93–0.94 / 0.87–0.93); graph facts 10/10 vs text 4/10 |
| 11 | Vector-store ADR: Qdrant vs pgvector on recall and latency | ADR with numbers | ✅ 2026-10-13: recall@10 tie (0.842) when exact or ef ≥ 100; p95 < 20 ms for all indexed options; keep Qdrant (ADR-0007 proposed) |
| 12 | CI regression (retrieval metrics on a committed mini fixture index, no secrets) + `just gate 2` | `just gate 2` passes; CI goes red when recall drops | ◐ 2026-10-13: fixture + ablation report + gate built; every check PASS except the golden review (task 3) |

Memory measured 2026-10-06 (core + fhir + rag, index loaded): **3.59 GB** of containers (Neo4j 1,127 MB, Qdrant 251 MB);
the encoder runs on the host (~1.7 GB while embedding), outside the WSL cap.

## Phase 3 — Agents + safety (weeks 6–7)

**Phase exit gate (SPEC §12):** the red-team suite passes 100%; no FHIR write without approval (tested).
Run with `just gate 3`.

**Decisions (you, 2026-10-13):** start Phase 3 before the Phase 2 golden review is in (waiver of the
phase-order rule; Phase 2 closes when the review lands). Review UI: minimal React (Vite) with plain CSS.
Free-tier budget: every LLM response cached; development on small subsets, as in Phase 2.

| # | Task | Exit-gate test | Status |
|---|------|----------------|--------|
| 0 | Dependencies (`langgraph`, `mcp`) with reasons; ACI-Bench licence | Licences recorded; lint + tests green | ✅ 2026-10-13 |
| 1 | `agents/schemas.py`: Pydantic contracts (Evidence, Interaction, PatientSummary, SOAP statements with transcript span + citations, approval token) | Schema unit tests; every tool input/output typed | ✅ 2026-10-13: 9/9 |
| 2 | MCP servers: `guidelines-mcp`, `druggraph-mcp`, `fhir-mcp` (`get_patient_context` audited; `write_fhir` refuses without a valid token) | Contract tests per tool over stdio; a read leaves an audit row | ✅ 2026-10-13: unit 14, stdio 4/4 |
| 3 | Retrieval as a service (models need torch, which the API image excludes): own image + memory limit | Health test; stack memory measured ≤ 8 GB | ✅ 2026-10-13: HTTP 2/2; stack 4.0 GB; p50 244–261 / p95 288–326 ms warm |
| 4 | LangGraph graph: intake → router → ask / note_writer → guardrail_check → hitl_review (`interrupt()`) → commit | Graph unit tests with scripted models; replay from a checkpoint | ✅ 2026-10-13: 11/11 incl. resume on a new graph instance |
| 5 | Ask agent: fast path + agentic loop (grading, query rewrite: Self-RAG/CRAG style); graph facts for drug questions; ablation step 7 (routing) | Router accuracy; answer quality vs fast path; cost | ✅ 2026-10-14: router interaction recall 14/20 (other questions agentic 25/215); 2026-10-27: answer quality fast vs agentic measured (`agents/router_quality.md`) |
| 6 | Note-writer: transcript → SOAP statements with spans and citations | Schema validity rate on ACI-Bench dialogues | ✅ 2026-10-14: 8 dialogues: 6 drafts, 5 clean on the first attempt; 2 long ones truncated |
| 7 | Guardrails (`config/guardrails.yaml`): input (injection, de-ID check) and output (citations, dose sources, diagnosis wording, schema); retry once, then safe reply | Unit tests per rule | ✅ 2026-10-13: 6/6 |
| 8 | Approval token (HMAC; bound to draft hash, approver, patient, expiry) + two-identifier check before any write | No write without token; tampered/expired/wrong-patient refused | ✅ 2026-10-13: fhir-mcp checks (task 2) + API signs the token for the exact resource at review; live approve → write |
| 9 | Auth + RBAC (doctor, admin, operator); `/reidentify` doctor-only | Access tests per role | ✅ 2026-10-13: 6/6 (401 no/forged/expired token, 403 by role); `/reidentify` itself was not built then: added 2026-10-24 (ADR-0015) |
| 10 | Review UI (React + Vite): drafts, unsupported statements highlighted, approve / edit / reject; edits saved as before/after pairs | End-to-end test; screenshots | ✅ 2026-10-13: driven in the browser against the live stack: draft → approve → DocumentReference/59139 |
| 11 | Red-team set (~60): unsourced doses, diagnosis wording, injections in documents/PDFs, PHI in output | `just eval redteam` 100% (cached) | ✅ 2026-10-13: 63/63; negative control 23/63 |
| 12 | ADRs: orchestrator (LangGraph vs Pydantic AI vs OpenAI Agents SDK on one task, isolated project) and A2A | ADRs with numbers | ✅ 2026-10-14: ADR-0008 (LangGraph; footprint + approval mechanisms measured, same-task build not done), ADR-0009 (A2A at the edge only) — proposed |
| 13 | `just gate 3` | Red-team 100%; no write without approval | ✅ 2026-10-14: `just gate 3` 5/5 PASS |

## Phases 5 and 6 (done before Phase 4 with your approval, 2026-10-14)

**Phase 5 exit gate (SPEC §12):** a turn completes with all cloud providers disabled — **PASS**
(`just gate 5`, together with the lab checks).
**Phase 6 exit gate:** every SPEC §14 item done — `just gate 6` runs the deliverables check
(`scripts/deliverables.py`); pending: voice WER and latency evidence, the voice ADRs, the demo video.

| Item | Status |
|---|---|
| All-cloud-down failover to local Ollama (`just chaos cloud-down`) | ✅ live: turn served by `clinscribe-fallback-local` |
| Lab mode: PDF → preliminary Observations, flags, confirm → final (`/v1/lab/*`, `parse_lab_report`) | ✅ 162/162 values at first, 155/155 since (see 2026-10-26), wrong-patient 20/20; HL7 v2 ORU^R01 added 2026-10-26 (ADR-0021) |
| LoRA fine-tune of the de-ID tagger (`finetune/`) | ✅ trained on Colab (you); round 1 rejected, round 2 adopted behind `DEID_NER=tagger` (ADR-0014) |
| Load test p50/p95 at 10 / 50 / 100 sessions (`evals/load`) | ✅ with before/after of the de-ID fix |
| Three injected incidents + postmortems (`evals/incidents`, `docs/postmortems`) | ✅ outage (found and fixed a fallback gap), drift, latency |
| Cost per consultation by model (`evals/llmops/cost_report.py`) | ✅ |
| Compliance pack, runbooks, contributor guide, README, write-up draft | ✅ |
| Voice (Phase 4): pipelines, WER benchmark, TTFA, voice ADRs | ✅ (see Phase 4 entry); demo video is yours |

## Done

- 2026-10-04: Task 1 — repo skeleton, uv project (Python 3.11), justfile, Settings + `.env.example`,
  `just doctor` / `just gen-keys`, ruff ban on provider SDKs outside the gateway. Verified on a clean clone:
  `just lint` clean, `just test` 25 passed.
- 2026-10-04: Task 2 — ADR-0001 (gateway scope), ADR-0002 (Langfuse Cloud), ADR-0003 (profiles and memory);
  ADR format test. `just lint` clean, `just test` 29 passed.
- 2026-10-04: Installed Python 3.11.11 (uv) and just 1.58.0 (`uv tool install rust-just`, in `D:\devcache\bin`).
  CLAUDE.md: vLLM removed, commands and layout updated; SPEC §10 tree synced.
- 2026-10-04: SPEC §12 roadmap written in; SPEC wording updated for free tiers, Gemini Live,
  Ollama-only local fallback and Langfuse Cloud; gateway-scope rule added to CLAUDE.md;
  branch renamed `master` → `main`; this file created.

- 2026-10-05: Task 0 — `.wslconfig` (memory 10 GB, 4 GB swap file on D:, autoMemoryReclaim);
  Docker CLI plugins repointed to `D:\Docker\app\resources\cli-plugins` (`~/.docker/config.json`,
  backup `config.json.bak-clinscribe`); Ollama 0.35.1 installed to `D:\Ollama` (signed by Ollama Inc.);
  `.env` created by `just gen-keys`.
- 2026-10-05: Task 3 files — Dockerfile, `docker-compose.yml` (profiles core/fhir, memory limits,
  127.0.0.1 ports), Postgres init (per-service logins), minimal LiteLLM and collector configs,
  `/health` apps, `just up/down/ps/logs/stats`, stack health tests. Images pulled (LiteLLM v1.104.0,
  HAPI v8.12.0-2, Postgres 16.15, collector 0.161.0). `just lint` clean; `just test` 41 passed,
  9 skipped (stack not started).

- 2026-10-05: Task 3 done — `just up` healthy in 636 s (mostly image downloads on a slow link);
  `tests/integration/test_stack_health.py` 9/9 passed; memory 1.94 GB. Full suite: `just lint` clean,
  `just test` 53 passed, 4 skipped (FHIR data not loaded yet). Provider and Langfuse keys added to `.env`.

- 2026-10-05: Task 4 done — Synthea v4.0.0 (SHA-256 checked), seed 42, 50 living patients, 52 bundles loaded
  in 1,147 s (mostly the 201 MB jar on a slow link). `tests/integration/test_fhir_data.py` 4/4 pass:
  count 50, every patient has an Encounter, family-name search, idempotent reload. Memory with data: 2.43 GB
  (HAPI 1.52 of 2 GB limit).
- 2026-10-05: Task 5 done — gateway aliases with the 4-step fallback chain (Gemini `gemini-3.5-flash` →
  Groq `openai/gpt-oss-20b` → OpenRouter `google/gemma-4-31b-it:free` → Ollama `llama3.2:3b`),
  app virtual key (30 rpm, $1/30d), `config/models.yaml`, `llmops/gateway/client.py` (accepts only
  `DeidentifiedText`, record/replay cache), `just chaos primary-down on|off`, `just gateway-keys`.
  `just test-live`: primary answers (spend log `gemini/gemini-3.5-flash|clinscribe-default`); with the primary
  down the turn succeeds via Groq (spend log `groq/openai/gpt-oss-20b|clinscribe-fallback-groq`); Ollama step
  skipped. `just lint` clean; `just test` 64 passed.

- 2026-10-05: Task 6 done — de-ID v0: Presidio with spaCy `en_core_web_md` for PERSON/LOCATION and explicit
  regex recognisers for 15 structured Safe Harbor types (keyword-anchored > exact format > NER on overlap);
  consistent surrogates per encounter (`PHONE_1`); mapping in `deid_mappings` with HMAC lookup + Fernet
  ciphertext (no plaintext); `/deidentify`; `just migrate`; `just eval privacy`
  (`evals/reports/privacy/deid_v0.md`): structured recall 1.000 on 200 seeded snippets, PERSON 0.95,
  LOCATION 0.75; p50 16.7 ms, p95 22.2 ms per snippet in-process. Found and fixed an eval bug (surrogate label
  `AGE_OVER_89_1` contains "91"). `just lint` clean; `just test` (stack required) 94 passed; memory 2.75 GB
  (deid 362 MB).
- 2026-10-05: Host URLs switched from `localhost` to `127.0.0.1` (Windows tried `::1` first: 30 s per
  Postgres connection vs 0.04 s); DB connections get `connect_timeout=10`.

- 2026-10-05: Task 7 done — `llmops/telemetry`: deny-by-default span redaction (19 allow-listed keys, string
  values scrubbed with the de-ID regexes), log `RedactionFilter`, W3C trace propagation, GenAI span in the
  gateway client; collector `redaction` processor (same allow-list, RE2 blocked values) → local file +
  Langfuse Cloud EU via basic auth; LiteLLM OTel callback with `turn_off_message_logging`. Langfuse retired
  `GET /api/public/traces` for organisations created after 2026-09-16, so reads use
  `/api/public/v2/observations`. `just lint` clean; `just test` 100 passed (stack required);
  `just test-live` 2 passed, 1 skipped; memory 2.86 GB.

- 2026-10-05: Task 8 done — migration 002: `audit_log` with identity `seq`, triggers that block UPDATE,
  DELETE and TRUNCATE for every role (owner included), `app` granted SELECT/INSERT only;
  `apps/api/audit.py`: HMAC-SHA-256 chain over prev hash + canonical JSON, advisory lock for ordering,
  `verify()` names the first broken row; `just audit-verify`; DB connection strings moved to `config/db.py`.
  Tests 8/8 (100 appends incl. 10 concurrent; app UPDATE/DELETE/TRUNCATE refused; owner blocked by trigger;
  tamper found at the exact seq inside a rolled-back transaction). `just lint` clean; `just test` 108 passed.

- 2026-10-05: Task 9 done — `POST /v1/dev/complete` (`apps/api/pipeline.py`): de-ID client → gateway with the
  versioned prompt `prompts/dev_complete.yaml` (`dev_complete@v1`) → audit row (actor, model, prompt version,
  trace id, token counts, PHI type counts; no PHI). Answer stays in surrogate form until Phase 3 auth.
  `just test-live`: one real request returns an answer, its audit row carries the same trace id, and
  Langfuse holds one trace with `POST /v1/dev/complete`, `POST /deidentify` and `chat clinscribe-default`
  spans (closes the deferred task 7 check). `just lint` clean; `just test` 111 passed; memory 2.91 GB.

- 2026-10-05: Task 10 done — `evals/privacy/leak_test.py` (`just eval leak`): 20 synthetic transcripts
  (Faker seed 1234, 66 seed values) through `POST /v1/dev/complete`, then scans the collector export,
  `docker compose logs`, Langfuse v2 observations, LiteLLM spend logs, the audit table and the de-ID
  mapping table. Run `f3d5918c`: **0 leaks in every sink, positive control 100% — gate b passes**
  (`evals/reports/privacy/leak_test.md`). First run flagged `AGE_OVER_89` in three sinks; evidence showed
  `"input_tokens": 100` matching the seeded age 100, so ages are now matched only in age context
  ("100-year-old", "aged 100"), with a regression test. `just lint` clean; `just test` 116 passed;
  audit chain OK (449 rows).
- 2026-10-05: Task 12 tooling written — `just gate 1` (`scripts/gate.py`: lint, full suite with the stack
  required, gates a/b/c, pipeline, audit chain), `just eval latency` (p50/p95 primary up vs down),
  `docs/runbooks/local-setup.md`; task 11 `.github/workflows/ci.yml` (lint + unit on PRs; stack tests on
  main). Fresh clone in `D:\devcache\tmp\clinscribe-clone`: `uv sync`, `just lint`, `just test-unit` pass;
  `just up` stopped by the C: guard (see Blockers). Not yet run: `just gate 1` from the clone, latency eval, CI.

- 2026-10-06: Ollama `llama3.2:3b` installed (1.9 GB, in `D:\devcache\ollama-models`). The `ollama pull`
  kept failing because IPv6 connections from this PC hang (`dial tcp [2606:4700:…]:443` timeouts); the blob
  was fetched over IPv4 with `curl -4`, SHA-256 checked, then placed in the store. Direct check (no stack):
  answers correctly; cold load 74.6 s; 37.8 tokens/s; runs 20% CPU / 80% GPU (2.9 GB with a 4096 context does
  not fit fully in 4 GB VRAM). C: dipped to 0.24 GB free while the model loaded, then recovered to 2.34 GB.

- 2026-10-06: After the reboot (IPv4 now preferred; page file still system-managed on C:), the GitHub repo
  `Tharindu1527/Clinscribe-Medical-AI-Platform` (private) exists and `main` is pushed; a history scan found
  none of the 14 `.env` secret values in any of the 18 commits. Fresh clone **from GitHub** passed
  `uv sync`, `just lint`, `just test-unit` (93), `just up`, `just migrate`, `just gateway-keys`,
  `just fhir-load`; during `just gate 1` C: fell to 0.91 GB (C: page file 2.66 → 3.11 GB) and the guard
  stopped the stack. First CI run failed: `astral-sh/setup-uv@v10` does not exist (only exact tags), fixed by
  pinning `v10.2.0`.

- 2026-10-06: The page-file change ended in a blue screen (bugcheck 0x1A MEMORY_MANAGEMENT, 0x3F) and was
  reverted; recommend Windows Memory Diagnostic. Measured with the stack down: each Ollama model load grows the
  C: page file 1,725 → 2,760 MB and it shrinks back on unload. Local fallback now uses `num_ctx 2048`
  (100% GPU, 2.3 GB, 54 tok/s) and `keep_alive 30s`. WSL capped at 6 GB for Phase 1 runs. CI fixes:
  `.artifacts/otel` created writable before `just up` (root-owned bind mount crash-looped the collector on
  Linux), FHIR lookups with `Cache-Control: no-cache` (HAPI's ~60 s search cache caused duplicate posts).
  Gate runs from the fresh clone: lint, full suite (117), (c) FHIR pass; one run also passed (a) including the
  local step; the C: guard (< 1 GB) stopped the stack during the live tests each time. Gemini
  `gemini-3.5-flash` free tier is **20 requests/day per model** (429 `RESOURCE_EXHAUSTED`); after the quota
  ran out the gateway failed over to Groq as designed, but the "primary answers" check failed.
  `just gate 1` now scopes (a) to the cloud fallback; the local-model check belongs to the Phase 5 gate.

- 2026-10-06: **Phase 1 exit gate PASS.** Fresh clone from GitHub at `9e300cb`: `just up` 80 s,
  `just gate 1` 508 s — lint, full suite, (c) FHIR, (a) failover, pipeline, (b) leak test, audit chain all PASS.
  Latency and memory in the tables above. CI run #3 (`33e7fd3`) green: lint-unit and integration.

- 2026-10-06: CI fix for a start-up race: `just up --wait` returns before HAPI serves (no shell, so no
  healthcheck), and with Synthea data cached `fhir-load` posted 1 s later and was dropped. The loader now
  waits for `/fhir/metadata` (≤ 300 s); reproduced and fixed locally. CI green on `a8d0733`: lint-unit and
  integration (with Langfuse secrets).

- 2026-10-06: Task 11 done — throwaway PR (`ci/red-check`, `assert 1 + 1 == 3`) showed CI red; PR closed and
  the branch deleted; ruleset `protect-main` (active, default branch) requires `lint-unit`.
  **Phase 1 complete.**

- 2026-10-06: **De-ID v1** (ADR-0004). Added an over-redaction measure (80 PHI-free clinical sentences): v0
  altered 17.5% (eponyms, place-named diseases, drug brands). v1 = spaCy `md` + context cues for names
  (titles, relation words, name before MRN/DOB) and places (`City, ST`, residence, referral source) + an
  eponym rule and a 19,079-term RxNorm lexicon (person names removed) applied to spaCy guesses. Results
  (`evals/reports/privacy/deid_v1_en_core_web_md.md`): seeded names 1.000, places 1.000, structured 1.000,
  over-redaction 0/80; frozen held-out set names 0.973, places 0.850. `en_core_web_lg` compared and
  rejected (held-out places 0.650, over-redaction 1/80, 702 vs 334 MB). Leak test run `89341a14`: gate b PASS
  and **0 of 66 seed values reached the LLM** (was 2). A first leak-test run crashed with an error my
  output filter hid; the rerun passed. `just lint` clean; `just test` 137 passed (stack required).

- 2026-10-06: Phase 2 plan approved (corpus scope, golden-set review, eval budget); ADRs 0001–0004 approved.
- 2026-10-06: **Phase 2 task 0** — licences verified at the source: WHO (4 docs, CC BY-NC-SA 3.0 IGO, from
  IRIS metadata), PMC OA (CC BY/CC0 only, checked per article), openFDA (CC0), DDInter 2.0 (CC BY-NC-SA 4.0).
- 2026-10-06: **Phase 2 task 1** — `just ingest` (`retrieval/ingest`, scope in `config/corpus.yaml`): 4 WHO
  guidelines (PDF outline sections), 48 FDA labels (newest single-ingredient prescription label per drug), 183
  PMC reviews (JATS, CC BY/CC0, 2016–2026) → 235 docs, 8,104 section-aware chunks (median 195 words), each with
  URL, section and licence. Quality fixes found by inspecting the output, each with a regression test: the FDA
  search returned combination products (e.g. "clarithromycin" → an H. pylori kit); veterinary reviews (equine
  asthma) excluded; WHO PDF text repaired (fontTools for CFF fonts; running headers; GRADE ☐/⊕/◯ glyphs; the
  PEN 2020 offset-29 font decoded, which also restored digits — `splitlines()` had turned "140/90" into
  "140/0"); unverified glyphs left as `[?]` (51, all in PEN charts) rather than guessed; LaTeX formulas →
  `[formula]`. Garbled chunks 0. `just lint` clean; 126 unit tests passed; corpus tests 6/6. Raw cache and
  corpus stay in `data/` (git-ignored, on D:).

- 2026-10-06: **Phase 2 task 2** — `rag` Compose profile: Qdrant v1.19.2 (API key, telemetry off, 1 GB limit) and
  Neo4j 5.26.31 community (heap 768 MB, page cache 512 MB, 1.5 GB limit), 127.0.0.1 ports, bash TCP healthchecks;
  `QDRANT_API_KEY`/`NEO4J_PASSWORD` from `just gen-keys`. Dense baseline (`retrieval/dense.py`, `just index`):
  embedding model changed from jina-v2 to `nomic-ai/modernbert-embed-base` (pinned commit) because jina needs
  `trust_remote_code` (**ADR-0005, proposed — please review**). CPU torch from the PyTorch index in a `rag`
  dependency group that the service image does not install. 8,104 chunks embedded in **66.5 min on CPU
  (2.03 chunks/s)**, upserted in 11 s; vectors cached in resumable 512-chunk shards (the first attempt was lost
  when the session ended mid-run); rerun with nothing changed: 8 s, 0 upserts. Warm query latency p50 94 ms
  (5 queries; p95 comes with task 4). Tests: rag 5/5 (`CLINSCRIBE_REQUIRE_RAG=1`), unit 6/6 for the index.
  Corpus and rag tests now gate on `CLINSCRIBE_REQUIRE_RAG` instead of `CLINSCRIBE_REQUIRE_STACK` (the CI
  integration job builds no corpus and would have gone red). Incidents: WSL hung (`wsl -l -v` and
  `wsl --shutdown` never returned); fixed by ending `wslservice.exe` and restarting the service. Memory pressure
  while pulling images grew the C: page file to 12 GB (C: down to 5.7 GB free); dropping the WSL file cache
  helped. `just lint` clean; `just test` 167 passed (stack + rag up).

- 2026-10-06: **Phase 2 task 3 (drafted, review pending)**. `evals/golden/golden_v1.jsonl`: 235 items,
  209 answerable (hypertension 43, diabetes 40, anticoagulation 40, respiratory 42, infections 44;
  WHO 43, FDA 81, PMC 85) and 26 unanswerable (11%, drugs absent from the corpus, checked). Drafted by
  Claude from a seeded, stratified chunk sample (`evals/golden/candidates.py`); answers are exact quotes;
  gold ids = every chunk containing the quote (150 items with 1, 52 with 2, 7 with 3–4; one wrong
  cross-drug match fixed). Validator (`just golden`): quote in each gold chunk, no 6-word copy from the
  source, absent terms absent, quotas. Review sheet `evals/golden/review/review_v1.csv` (49 rows, 21%,
  every stratum; `just golden-review summary` checks it). Found while drafting (not fixed, see Open
  questions): WHO 344424 section titles come from figure bookmarks, and reference lists are indexed as
  chunks. Unit 6/6, integration 1/1; `just lint` clean; `just test` 174 passed.

- 2026-10-06: **Phase 2 task 4** — retrieval harness `evals/rag` (`just eval rag`): recall@1/5/10
  (answer-level: any gold chunk in the top k), MRR@10, nDCG@10 (binary, all gold chunks), breakdowns by
  area / source / question type, query latency p50/p95, misses list; rankings saved per system
  (`evals/reports/rag/runs/`) and `--compare A B` gives a paired bootstrap 95% CI per metric (for the
  ablation steps). **Dense baseline** (`evals/reports/rag/retrieval_dense.md`, 209 answerable questions):
  recall@1 0.435, recall@5 0.722, **recall@10 0.809**, **MRR@10 0.562**, **nDCG@10 0.583**; query
  latency (CPU embed + Qdrant) **p50 94 ms, p95 150 ms**. Weakest: respiratory (recall@10 0.690), diabetes
  0.750, WHO passages 0.767; best: dose questions 0.958, hypertension 0.930. Median top-1 similarity
  0.694 answerable vs 0.582 unanswerable (overlapping; not an abstention rule on its own). Spot check of 6
  of the 40 misses: 2 had a chunk giving the same answer in other words in the top 3 (e.g. idarucizumab),
  so recall is a lower bound (see Open questions); some misses found the right label but the wrong
  section (valsartan strengths), which reranking should help. Metric unit tests on hand-worked cases 6/6,
  harness integration 1/1. `just lint` clean; `just test` 181 passed.

- 2026-10-06: **Phase 2 task 5 (ablation step 2)** — `retrieval/bm25.py` (own Okapi BM25, Lucene IDF,
  k1 1.2, b 0.75, chunk text only like the dense index, stopwords without negations, plural folding; no
  `rank-bm25`, unmaintained since 2022), `retrieval/hybrid.py` (dense and BM25 in parallel threads, RRF
  k 60, depth 50, both untuned). Results (`evals/reports/rag/compare_*_vs_dense.md`, paired bootstrap):
  BM25 alone recall@10 0.699 (−0.110, CI [−0.182, −0.038]); **hybrid recall@10 0.813 (+0.005, CI
  [−0.048, +0.057]), MRR@10 0.533 (−0.028, CI [−0.074, +0.017]) — not shown better than dense**. The
  methods are complementary: BM25 finds 19 questions dense misses at 10, either finds 0.900 at 10 and
  0.943 at 20; hybrid's pool has the answer in its top 20 for 0.904 vs 0.876 dense (+0.029, CI
  [−0.010, +0.072]). Hybrid latency p50 111 ms, p95 161 ms (BM25 index built in-process from the corpus).
  Unit tests 7/7 (hand-worked BM25 and RRF values). `just lint` clean; full suite 188 passed (run with
  `uv run --no-sync`: the internet dropped and `uv run` re-checks the spaCy wheel URL).

- 2026-10-06: **Phase 2 task 6 (ablation step 3)** — `retrieval/rerank.py` (cross-encoder, ColBERT,
  `RerankedRetriever` over 30 first-stage candidates) and `retrieval/colbert.py` (Stanford ColBERT
  encoding implemented directly: PyLate pins sentence-transformers 5.3 / transformers ≤ 5.3; parity with the
  authors' ONNX export max |diff| 2.6e-7, `evals/rag/colbert_parity.py`). Models pinned, Apache-2.0, no
  remote code: `ms-marco-MiniLM-L6-v2` (22M), `answerai-colbert-small-v1` (33M). ColBERT store
  (`just index-colbert`): 8,104 chunks, 1.7M token vectors, 326 MB float16 on D:, 14 min at 9.7 chunks/s,
  memory-mapped. Results vs dense (95% paired bootstrap): cross-encoder not shown better on any metric and
  2.5–3.9 s per query; **hybrid + ColBERT recall@10 0.876 (+0.067, CI [+0.019, +0.115]), nDCG@10 0.638
  (+0.054, CI [+0.015, +0.095]), MRR@10 0.607 (+0.046, CI [−0.001, +0.093]), p50 157 ms / p95 229 ms**;
  dense + ColBERT recall@10 0.852 (CI [+0.000, +0.086]), MRR and nDCG better; hybrid vs dense pool under
  ColBERT +0.024 recall@10, not shown. **ADR-0006 (proposed): hybrid + ColBERT is the best pipeline so
  far**; BM25's benefit over dense + ColBERT is re-checked in task 12. ColBERT scores do not separate
  unanswerable questions (median top-1 30.8 vs 30.3): abstention must come from generation (task 10).
  Unit 7/7, integration 2/2. `just lint` clean; `just test` 197 passed.

- 2026-10-06: **Phase 2 task 7 (ablation step 4, contextual retrieval)** — `retrieval/contextual.py` and
  `prompts/contextual_prefix.yaml` (v1): the local `llama3.2:3b` writes a ≤ 60-word prefix per chunk from
  the title, source, section heading and the first 600 words of the section (Anthropic's prompt adapted to a
  2,048-token context; chunks of a section share the prompt prefix for Ollama's cache). New gateway key
  `clinscribe-batch` (`LITELLM_BATCH_KEY`, `just gateway-keys`): local alias only, 240 rpm, verified 403 on
  cloud aliases, so the job cannot spend free-tier quota. 8,104 prefixes in 3 h 20 min (0.68/s, p50 1.3 s,
  ~1,300 input / 50 output tokens), cached and resumable (`data/corpus/contextual/v1/`); median 36 words;
  0.4% contain a number absent from their chunk/title/section (section numbers from the excerpt). Re-indexed
  with `--variant contextual`: dense 81 min, ColBERT 14 min (359 MB). Results (paired bootstrap):
  **hybrid + ColBERT + context vs best so far (hybrid + ColBERT): MRR@10 0.680 (+0.073, CI [+0.028,
  +0.118]), nDCG@10 0.695 (+0.057, CI [+0.018, +0.095]), recall@1 0.565 (+0.096), recall@10 0.909 (+0.033,
  CI [−0.010, +0.077])**; vs dense baseline recall@10 +0.100 (CI [+0.053, +0.148]), MRR +0.119; latency
  p50 144 ms / p95 191 ms (no query-time cost). BM25 gains most (recall@10 0.699 → 0.799, +0.100, CI
  [+0.057, +0.148]); dense alone +0.033 recall@10 (n.s.), nDCG +0.040 (yes). Best so far is now hybrid +
  ColBERT over the contextual corpus. Incident: during the prefix run the C: page file grew 9 → 15 GB (Ollama
  llama-server 8 GB commit + WSL 7.5 GB), C: fell to 2.9 GB; stopped unneeded services and dropped the WSL
  cache, then ran with a monitor that would pause the job below 1.5 GB (not triggered). A reboot shrinks
  the page file. Unit 6/6 (contextual). `just lint` clean; `just test` 203 passed.

- 2026-10-07: **Phase 2 task 8 (ablation step 5, late chunking)** — `retrieval/late_chunking.py`: the same
  ModernBERT Embed encodes each whole section ([CLS] "search_document:" section [SEP], ≤ 4,096 tokens;
  44 longer sections in windows overlapping by 1,024; a chunk longer than the overlap gets its own centred
  window, found when 10 table chunks of up to 1,753 tokens stopped the first run at shard 12 — cached shards
  resumed), and each chunk vector is the mean of its own token vectors. Checks: exact parity with
  sentence-transformers when pooling all tokens (same token ids, cosine 1.000000); single-chunk sections
  0.989–0.9995 similar to the dense vectors. Build ~70 min on CPU (1.5–2.2 chunks/s), collection
  `chunks_dense_modernbert_late`. **Result: worse.** dense_late recall@10 0.727 vs dense 0.809 (−0.081, CI
  [−0.129, −0.038]) and vs dense_ctx 0.842 (−0.115); hybrid + ColBERT + late 0.861 vs + context 0.909
  (−0.048, CI [−0.091, −0.005]). Cause: chunk vectors of long sections converge (mean within-section cosine
  0.923 vs 0.706) and the loss grows with section length (sections of > 20 chunks 0.850 → 0.600; 2–5 chunks
  0.845 → 0.825); ModernBERT Embed was not trained for long-context pooling. **Rejected; contextual retrieval
  stays.** Note added to ADR-0005. Unit 6/6. `just lint` clean; `just test` 209 passed.

- 2026-10-08: CI fix: the ColBERT rerank integration test read `data/corpus` before checking it exists, so
  the CI integration job (no corpus) failed instead of skipping (not Langfuse). Fixed; CI-like run skips,
  full local run with `CLINSCRIBE_REQUIRE_RAG=1` 37/37.
- 2026-10-08: **Phase 2 task 9 (ablation step 6, GraphRAG)** — `retrieval/graph/` (`just graph`):
  DDInter 2.0, all 14 ATC-group CSVs (the download page links 8; C and J hold the cardiovascular and
  anti-infective pairs), SHA-256 recorded; 1,971 drugs, **234,981 unique pairs** (Moderate 143,748, Unknown
  42,415, Major 39,082, Minor 9,736; no level conflicts). RxNorm via RxNav (cached): 1,895 drugs (96%) mapped
  to an ingredient RxCUI, 1,367 with brand names (29 min at ~1.6 calls/s). Lexicon: DDInter + ingredient
  names, salt/ester-free aliases (lithium carbonate → lithium, dabigatran etexilate), co-trimoxazole and
  co-amoxiclav, capitalised brands only; everyday substance words excluded ("glucose", "oxygen") after a
  first 5%-frequency rule wrongly dropped warfarin (479 chunks). Neo4j via the HTTP API (no driver):
  `(:Drug)-[:INTERACTS_WITH {level}]-(:Drug)`, `(:Chunk)-[:MENTIONS]->(:Drug)` 8,625 edges over 3,475
  chunks; load 28 s, idempotent by fingerprint. 46 of 47 corpus drugs are in DDInter (**dabigatran is not**).
  GraphRAG: a router (two different drugs, or one drug + an interaction cue) adds co-mention and
  label-interaction-section chunks to the hybrid pool before ColBERT. Router v1 caught 10 of 19 interaction
  questions; v2 (rules widened after reading the golden questions, so optimistic) 17 of 19, 28 of 209 routed.
  **Result: no retrieval gain** — interaction subset identical (recall@10 0.895, 17/19, both systems; the 2
  misses are not routable: dabigatran absent, "insulin" generic); routed subset +1 question (+0.036, CI
  [0.000, +0.107]); full set recall@10 0.914 vs 0.909 (+0.005, n.s.); +74 ms p50 on routed questions
  (same-day timing: both systems p50 ~350 ms today vs 144 ms on 2026-10-06, machine load). Every golden
  question was drafted from a corpus passage, so this set cannot show the graph's main value (pairs the
  corpus never discusses). **Decision: graph candidates stay out of the default retrieval pipeline; the
  interaction facts (`GraphRetriever.facts()`) go to task 10 with graph-only questions.** Unit 8/8,
  integration 5/5. `just lint` clean; `just test` 222 passed.

- 2026-10-08: **Phase 2 task 10 (in progress)** — `retrieval/generate.py` + `prompts/answer_cited.yaml` v1:
  top-5 chunks labelled [S1]..[S5], JSON sentences each citing labels (mapped to chunk ids), re-validated,
  one retry with the error, then the safe reply. Judge `prompts/judge_citations.yaml` v1 on a new alias
  `clinscribe-judge` (Groq gpt-oss-120b; not a fallback target): per-sentence support by the cited and by
  any chunk, plus whether the answer conveys the golden quote. `evals/rag/answer_eval.py` (`just answers`):
  seeded stratified 60-question subset (10 answerable + 2 unanswerable per area), contexts from the stored
  rankings (same passages, no retrieval cost), LLM responses cached in `data/llm_cache/`, waits out per-minute
  limits, stops cleanly on the daily budget and resumes. Generator Groq gpt-oss-20b for every pipeline (the
  Gemini pool's 20 requests/day per model would force a mid-run model switch). Measured cost ~2.1k tokens per
  answer and ~2.5k per judgment; **Groq's free daily budget ran out at ~111k tokens (generator), so ~47
  answers per model per day** (a 57,600 s wait was requested). Decision (you): keep the same models and
  finish over the next days. Interim dense baseline, 52 of 60 questions: faithfulness 0.937, citation
  precision 0.926, correctness 0.76, false abstentions 18% of answerable, correct abstentions 100% of
  unanswerable, 0 judge errors. Also built: graph-only check (`evals/rag/graph_facts_eval.py`, 10 Major
  DDInter pairs no chunk names together; DDInter facts as citable `graph:ddinter:` sources) and a RAGAS
  cross-check (`evals/rag/ragas_check.py`, throwaway env with langchain < 1 because ragas 0.4.3 imports a
  module removed from langchain-community 0.4; Gemini pool, a different model family from the judge).
  Unit 7/7 (answers), gateway config test updated for the judge alias. Lint clean; unit tests 187 passed.
- 2026-10-08: The app key hit its **$1/30-day LiteLLM budget** ($1.30 notional; LiteLLM prices free-tier calls
  at list price, $0 billed) and refused RAGAS calls. Raised to a **$25 notional usage cap** (`just gateway-keys`;
  comment in `scripts/gateway_keys.py`); the free tiers' daily limits stay the real ceiling. **RAGAS cross-check,
  dense half** (`evals/reports/rag/ragas_calibration.md`, 10 answers, Gemini pool): agreement on "fully
  faithful" 10/10, Spearman 1.00, mean faithfulness RAGAS 0.970 vs our judge 0.925 (ours is stricter: whole
  sentences vs RAGAS's smaller claims). Groq budget resets ~10:30 on 2026-10-09.
- 2026-10-09: **Phase 2 task 10, answers measured** (Groq gpt-oss-20b generator, gpt-oss-120b judge, cached).
  Dense finished 60/60: faithfulness 0.937, citation precision 0.926, correctness 0.76, false abstentions 18%
  of answerable, correct abstentions 100%. Best pipeline (hybrid + ColBERT + context) 57/60 before Groq asked
  for a 6 h wait (all 50 answerable done; 3 unanswerable left, they only change the abstention rate).
  Paired comparison (`evals/reports/rag/answers_hybrid_colbert_ctx_vs_dense.md`, 95% bootstrap):
  **correctness 0.760 → 0.910 (+0.150, CI [+0.050, +0.260])**, false abstentions 18% → 2%, answered 41 → 49
  of 57; **faithfulness 0.937 vs 0.941 (+0.004, CI [−0.049, +0.069], not shown better)** on the 41 questions
  both answered; citation precision 0.926 vs 0.875 (−0.051, CI [−0.124, +0.028], not shown worse). The dip is
  mostly "partial" links on sentences citing 2+ sources (best 21 partial / 5 no of 140 links; dense 7 / 2 of
  102), i.e. over-attribution rather than unsupported claims. Reading: better retrieval turns abstentions into
  correct answers; faithfulness is at a ceiling for both because the generator abstains rather than guesses.
  **RAGAS cross-check complete** (`evals/reports/rag/ragas_calibration.md`, 20 answers, Gemini pool):
  "fully faithful" agreement 20/20, means RAGAS 0.985 vs ours 0.963; Spearman 1.00 rests on only 2 non-perfect
  scores, so it is weak evidence of ranking agreement. RAGAS sampling now draws from answerable questions only
  (dense sample unchanged, checked). `just lint` clean; `just test` 229 passed (stack + rag up).
- 2026-10-09: Groq's daily limit is a **rolling window** (a probe 3 h before the stated wait succeeded). Best
  pipeline finished 60/60 (the last 3 unanswerable, all correct abstentions); the comparison is unchanged.
  **Graph-only check** (`evals/reports/rag/answers_graph_facts.md`, 10 Major DDInter pairs that no chunk names
  together): text only answered 4/10 (interaction stated 0.40, faithfulness 0.62; one answer, diltiazem +
  edoxaban, stated the interaction while citing a chunk that does not support it, faithfulness 0 — the
  hazard the citation check exists for); text + DDInter facts answered 10/10, stated 1.00, cited the graph
  10/10, faithfulness 0.95. Small n, illustrative; supports giving the agent the graph facts in Phase 3.
- 2026-10-10: **Phase 2 task 10 done.** Runner-up `hybrid_colbert` 60/60. vs dense: correctness 0.760 →
  0.860 (+0.100, CI [+0.010, +0.190]), false abstentions 18% → 6%, faithfulness +0.006 (CI [−0.073, +0.085]),
  citation precision −0.056 (CI [−0.150, +0.042]). Context prefixes on top (`hybrid_colbert_ctx` vs
  `hybrid_colbert`): correctness +0.050 (CI [−0.030, +0.140], not shown), false abstentions 6% → 2%,
  faithfulness and citation precision unchanged. Reports `evals/reports/rag/answers_*.md`. Summary: retrieval
  quality shows up as **correctness and answer rate**; faithfulness sits at ~0.94 for every pipeline because
  the generator abstains rather than guesses. `just lint` clean; `just test` 228 passed, **1 failed**:
  `test_trace_arrives_in_langfuse_without_phi`, because Langfuse Cloud answers ingestion with 403 "Ingestion
  suspended: Usage threshold exceeded" (keys valid, reads return 200; see Blockers).
- 2026-10-13: Docker stopped starting (`HCS_E_HYPERV_NOT_INSTALLED`): the Windows hypervisor had not launched
  since 2026-10-11 (`hypervisorlaunchtype` off). You set it back to auto; stack, volumes and data were intact.
- 2026-10-13: **Tracing volume cut** (Langfuse quota). Measured per gateway call in the collector file: LiteLLM
  sent 7–8 spans, 5–6 of them internal service spans (auth, proxy_pre_call, router ×2, self, postgres,
  batch_write_to_db) with no GenAI data. Collector `filter/litellm_internal` now keeps only `litellm_request` and
  `Received Proxy Server Request` (2 spans per call). LiteLLM's per-key callback disabling is Enterprise-only,
  but the request flag `"no-log": true` works in OSS: `GatewayClient(trace=False)` sends it (outside the cache
  key, so cached responses still replay) for the contextual-prefix batch job, the answer, graph-facts and RAGAS
  evals; measured 0 spans per call, spend logs still recorded (corrected 2026-10-25: a no-log call gets
  no spend-log row at all). Unit tests +2. `just lint` clean; `just test` 230
  passed, 1 failed (Langfuse ingestion still suspended).
- 2026-10-13: **Phase 2 task 11 (vector store).** `pgvector` service (`pgvector/pgvector:0.8.6-pg16`, own
  `vectorstore` profile, 768 MB limit, `PGVECTOR_PASSWORD` from `just gen-keys`), `retrieval/pgvector_store.py`
  (COPY of the cached contextual vectors, cosine HNSW, exact search with index scans off),
  `evals/rag/vectorstore_eval.py` (`just vectorstore`, report `evals/reports/rag/vectorstore.md`). Found: the
  deployed Qdrant collection is **not HNSW-indexed** (6 segments below the 10 MB indexing threshold, 0 of
  8,104 indexed), so every Phase 2 dense result is exact search. Four runs, same query vectors, HNSW m 16 /
  ef_construct 100 in both: recall@10 0.842 for Qdrant (exact and HNSW) and pgvector (exact and HNSW
  ef_search 100); pgvector at its default ef_search 40 loses 0.014–0.024. Store-only p95: Qdrant 12.6–16.8 ms,
  Qdrant HNSW 12.1–16.4 ms, pgvector HNSW ef100 8.4–11.9 ms, pgvector exact 88–115 ms. Memory: pgvector 114
  MB vs Qdrant 468–533 MB (four collections). **ADR-0007 (proposed — please review): keep Qdrant**; pgvector
  with ef_search ≥ 100 is the measured fallback if Phase 4 memory forces a service out. Unit 3/3,
  integration 2/2. `just lint` clean; `just test` 236 passed, 1 failed (Langfuse ingestion suspended).
- 2026-10-13: **Decisions (you):** Phase 2 gate = recall@10 and answer correctness better than dense-only,
  faithfulness non-inferior (margin 0.05); SPEC §12 updated. CI fixture without WHO text (CC BY-NC-SA).
  Recall reported as a quote-based lower bound (no pooled judgements).
- 2026-10-13: **Phase 2 task 12 (tooling done).** CI regression: `tests/fixtures/rag_mini/` (100 golden
  questions, FDA + PMC only, 1,205 chunks, float16 ModernBERT vectors for chunks and questions, 3.8 MB,
  licence README; built by `evals/rag/fixture.py`) and `tests/unit/test_rag_regression.py`: dense, BM25 and
  hybrid RRF recompute recall@10 and MRR@10 with the production code, no models, no corpus; thresholds 0.01
  below measured (dense 0.83, BM25 0.74, hybrid 0.86 recall@10). Red check done locally: removing
  lowercasing in the BM25 tokenizer failed BM25 and hybrid; restored, green. `evals/rag/ablation.py` writes
  `evals/reports/rag/ablation.md` from the stored runs and answer rows (no LLM calls) and checks the gate
  criteria; the 8 systems in it were re-timed back to back (rankings identical to before, 235/235 each):
  chosen pipeline p50 159 / p95 206 ms, dense 106 / 143 ms. BM25 re-check (ADR-0006 update): without BM25
  recall@10 0.890 vs 0.909 (−0.019, CI [−0.043, +0.005]), 23–32 ms cheaper; BM25 kept. `just gate 2`
  (`scripts/gate.py`): lint PASS, golden validator PASS, CI fixture PASS, **criteria PASS** (recall@10 +0.100
  [+0.053, +0.148]; correctness +0.150 [+0.050, +0.260]; faithfulness +0.004 [−0.049, +0.069]); **FAIL**: the
  golden review sheet is empty (task 3) and the full suite's Langfuse test (ingestion suspended). Also fixed:
  the pgvector tests used the rag flag, so they errored with the `vectorstore` profile stopped; they now use
  `CLINSCRIBE_REQUIRE_VECTORSTORE`. Unit tests +6 (regression 4, ablation 2). `just lint` clean; `just test`
  240 passed, 2 skipped (pgvector off), 1 failed (Langfuse ingestion suspended).
- 2026-10-13: **Langfuse treated as non-essential (you).** The current keys stay; the Langfuse delivery test
  now probes the ingestion endpoint first and skips, with the reason, only on Langfuse's exact
  "Ingestion suspended" refusal (any other failure still fails). The local-export test keeps checking that
  spans carry no PHI. `just gate 2`: lint, full suite (240 passed, 3 skipped: Langfuse + 2 pgvector), golden
  validator, CI fixture and the gate criteria all PASS; **only the golden review (task 3) FAILS**.
- 2026-10-13: **Phase 3 task 0.** `langgraph` 1.2.12 and `mcp` 2.2.0 (both MIT, released ≥ 2 weeks before
  adding), `langgraph-checkpoint` held at 4.2.0 (4.3.0 was a day old); added with `uv lock --upgrade-package
  <pkg>==<ver>` so no existing package moved (a plain `uv add` had also upgraded 26 unrelated packages,
  including ruff and pydantic, and was reverted). New transitive packages include `langsmith` (pulled by
  langchain-core); it only sends data when `LANGSMITH_TRACING` is set, which this project never sets.
  ACI-Bench: CC BY 4.0 per its README (no LICENSE file); how the dialogues were produced is checked against
  the paper before ingest.
- 2026-10-13: **Phase 3 task 1.** `agents/schemas.py`: strict Pydantic contracts (unknown fields are errors)
  for the four Phase 3 tools and the agent outputs. Safety rules live in the models: a note statement needs
  transcript turns or a citation; assessment/plan statements without a citation are listed for the doctor
  (`SoapNote.unsupported()`); every answer sentence cites; `PatientSummary` has no name, birth date or
  address and caps age at 90; a FHIR write carries an approval token (doctor only, expiry after issue, draft
  SHA-256) and two identifiers naming the same patient; drafts are always `ai_generated`. Unit 9/9.
- 2026-10-13: **Phase 3 task 2 (MCP servers)** on the mcp 2.x SDK (`MCPServer`, `ToolError` so refusal
  reasons reach the model). `fhir-mcp`: `get_patient_context` (age capped at 90, sex, active conditions and
  medications, allergies; no name, birth date or address) audits every read with the requesting user
  (`requested_by` + role added to the contract); `write_fhir` refuses, with the reason and an audit row,
  unless the approval token (`agents/approval.py`: HMAC-SHA-256 over canonical claims with
  `APPROVAL_TOKEN_KEY`, constant-time compare, 10-min expiry, bound to the SHA-256 of the exact resource)
  verifies, the resource type is writable, both identifiers (id + birth date + family name) match the record
  and the resource is about that patient; the create is conditional on the draft id, so a replayed token
  writes once (`fhir.write.duplicate`). `druggraph-mcp`: `check_interactions` returns DDInter pairs with
  citable ids and **the names it could not match** (`InteractionReport.unknown_drugs`, e.g. dabigatran), so
  "no interaction" never hides "unknown drug". `guidelines-mcp`: `search_guidelines` over the chosen pipeline
  (`retrieval/pipeline.py build_chosen()`), source/topic filters, original chunk text; the query goes through
  the de-ID service again before the encoders. Tests: unit 14 (servers in-process with fakes) + 5 (approval);
  stdio integration 4/4 against the stack (real HAPI read + audited, approved write + replay + wrong-family
  refusal, Neo4j, retrieval with the models; 58 s). `just lint` clean; `just test` 272 passed, 3 skipped.
- 2026-10-13: **Phase 3 task 3 (retrieval as a service).** Dockerfile now has two targets: `app` (default,
  unchanged for every existing service; CI builds only this one) and `rag` (adds the CPU torch group;
  2.7 GB vs 0.97 GB). `guidelines-mcp` service in the `rag` profile serves `search_guidelines` over
  streamable HTTP on 127.0.0.1:8010 (2.5 GB limit), models from the host Hugging Face cache and the corpus/
  indexes from `./data`, both read-only, offline mode; one warm-up query before the port opens (first query
  14 s → 1.3 s). Found and fixed before commit: a required `HF_HOME` in the mount broke every `--profile "*"`
  command (CI has no HF_HOME); it now defaults to `./data/hf-cache`. Latency over HTTP, 40 golden questions,
  including the de-ID round trip: **first pass after start p50 457 / p95 756 ms, warm p50 244–261 / p95
  288–326 ms**; host over stdio p50 215 / p95 358 ms. Tried and dropped: a Docker volume instead of the bind
  mount (warm 245/288 ms, same as bind) and prefetching the ColBERT store at start-up (first pass unchanged),
  so the cold first pass is not file I/O; cause not isolated (likely per-shape warm-up in torch). Memory with
  core + fhir + rag: **4.0 GB** (guidelines-mcp 0.62 GB). Integration 2/2 (HTTP, contract rejection).
  `just lint` clean; `just test` 274 passed, 3 skipped.
- 2026-10-13: **Phase 3 tasks 4, 7, 8, 9 (+ the runtime of 5 and 6).** `agents/graph.py` (LangGraph): intake
  (structured-PHI re-check) → router → fast path or agentic loop (CRAG-style grading, one query rewrite, DDInter
  facts for drug questions) → cited answer → guardrails (one retry with the violations, then the safe reply);
  scribe: note_writer → guardrails (one retry, then failing statements removed and listed) → `interrupt()` for
  the doctor → commit via `write_fhir`. Guardrails (`config/guardrails.yaml`, `agents/guardrails.py`): PHI in
  model input, injection in evidence (passage dropped before any model sees it), unsourced doses (number +
  unit must appear in a cited source or, for notes, in the cited transcript turn), invented citations,
  diagnosis wording, unknown transcript turns. New prompts `note_writer`, `grade_evidence`, `rewrite_query`
  (v1). All three MCP servers run as HTTP services (`fhir-mcp` in `fhir`, `druggraph-mcp` and
  `guidelines-mcp` in `rag`). API: HMAC bearer tokens with roles from `config/users.yaml` (synthetic demo
  users; `just token <user>`; `/v1/dev/login` only with `DEV_LOGIN=true`), `/v1/ask`, `/v1/scribe/drafts`,
  `/v1/drafts/{id}`, `/v1/drafts/{id}/review` (the API signs the approval for the exact FHIR resource the
  reviewed note becomes; fhir-mcp re-verifies), `/v1/audit` (admin/operator). Drafts live in an in-memory
  checkpointer (an API restart drops pending drafts; see Open questions). **Live end-to-end 2/2**: a cited Ask
  answer, and a synthetic consultation → draft → doctor approval → DocumentReference in HAPI, with the audit
  chain `ask`, `draft.create`, `fhir.write`, `draft.approve`. Mistake caught and fixed: the agent-graph tests
  first overwrote Phase 2's `tests/unit/test_graph.py`; restored as `test_drug_graph.py`, new tests in
  `test_agent_graph.py`. Unit +17, integration +6, live +2. `just lint` clean.
- 2026-10-13: **Phase 3 task 10 (review UI)**, `apps/web` (React 19.3 + Vite 8.3, plain CSS, `npm --prefix
  apps/web run dev`; Vite proxies `/v1` to the API): sign-in with demo users (`DEV_LOGIN=true` set in the local
  `.env`), Ask with numbered citations and sources, Scribe draft review by SOAP section with unsupported
  statements highlighted, edit / approve with two identifiers / reject, audit log for admin and operator.
  Driven in the browser pane against the live stack: transcript → draft (6 statements, 4 flagged) → approve
  → "Saved to FHIR: DocumentReference/59139".
- 2026-10-13: **Phase 3 task 11 (red team).** `evals/redteam` (`just eval redteam`): 63 cases (unsourced doses
  15, diagnosis wording 10, invented citations 5, injected passages 10, PHI in input 8, bad note statements 6,
  writes without a valid approval 9) through the real graph, guardrails and fhir-mcp code with a scripted model
  that misbehaves on every attempt: **63/63 pass**. Negative control (`--control`, rules switched off in the
  system, checker strict): 23/63, so the suite can fail. No LLM calls.
- 2026-10-14: **Phase 3 tasks 5, 6, 12.** Router (ablation step 7, `evals/reports/agents/router.md`): comparison
  wording alone sent 2/20 interaction questions to the agentic path; adding the Phase 2 graph router's cues
  gives 14/20 (25/215 other questions go agentic, ~1 extra grading call each); adopted (optimistic: those cues
  were widened on the golden set). Note writer on 8 ACI-Bench dialogues (de-ID per turn, real model,
  `evals/reports/agents/note_writer.md`): 6 drafts, 5 clean on the first attempt, ~25 statements each, 3
  unsourced doses removed; the 2 longest consultations (59, 81 turns) failed twice with truncated JSON (4,500
  output tokens is the most Groq's free per-minute limit leaves); p50 67 s per draft (Gemini 503s, then
  fallback). Two fixes found on the way: Groq's JSON mode rejected valid long notes (`json_validate_failed`),
  so graph prompts no longer use provider JSON mode (the graph parses and validates itself); note_writer
  v2 raises max_tokens 3,000 → 4,500. ADR-0008 (orchestrator: LangGraph; 40 / 19 / 41 packages for LangGraph /
  Pydantic AI / OpenAI Agents SDK, all three ship tool-level approval, only LangGraph pauses on graph state
  with per-step checkpoints; the same-task build was not done) and ADR-0009 (A2A only at the edge, e.g. a
  referral hand-off). `just gate 3` added.
- 2026-10-14: **Phase 3 exit gate PASS** (`just gate 3`, second run): lint; full suite 299 passed, 3 skipped
  (stack + rag required); red-team 63/63; no-write-without-approval tests 40/40; live end-to-end 2/2. The
  first run failed the live step: the API's gateway client timed out at 120 s while a note waited out Gemini
  503s and the fallback chain (it returned a bare 500). Fixed: 300 s timeout for the API's model calls, and
  gateway timeouts / failures now return 504 / 502 with a message. **Phase 3 complete.**
- 2026-10-14: **Phase 5.** `just chaos cloud-down` (Gemini, Groq, OpenRouter pointed at a dead address):
  a live turn completed on local Ollama and the spend log records `clinscribe-fallback-local` (~2 min with
  the cold model load). Lab mode: `agents/lab` (a ~40-line PDF writer, deterministic pypdf parser; no model
  sees lab values), `config/lab_reference.yaml` (illustrative adult intervals), `parse_lab_report` on
  fhir-mcp (audited, identity check against the record), `/v1/lab/parse` and `/v1/lab/{id}/confirm`
  (each value written as a final Observation with its own approval; a report whose name or birth date do not
  match is refused 409). Eval (`evals/reports/lab/lab_parser.md`): 20 patients, 162/162 values mapped,
  exact and flagged (17 abnormal), wrong-patient control 20/20; one fixed synthetic layout, no scanned
  images. LoRA kit: `finetune/make_dataset.py` (5,000 seeded synthetic sentences, hard negatives) and a Colab
  notebook (`distilbert-base-cased` + LoRA r 8). **`just gate 5` PASS** (second run: the first failed one
  settings test because I edited `.env.example` while the suite ran).
- 2026-10-14: **Phase 6.** Load (`evals/reports/load/load_test.md`, mock model via a new `clinscribe-mock`
  alias and a mock-only `clinscribe-load` key): 10 / 50 / 100 sessions, 0 errors; spans showed de-ID (one
  process, called twice per question) queueing to p95 26 s; **3 uvicorn workers** cut p95 at 10 sessions
  13.9 → 2.9 s and tripled throughput (1.7 → 5.1 req/s); guideline search (CPU) is the next limit.
  Drills (`evals/incidents/drills.py`): **outage** — 2/4 agentic questions failed (502) although failover
  worked, because answers are bound to the Groq alias, which had no fallback; fixed with a Groq → OpenRouter
  → local chain and logging of gateway failure type/status; re-run 4/4. **Drift** — replayed the
  late-chunking index: recall@10 −0.048, MRR −0.081 (CIs exclude 0); the CI fixture would not catch it.
  **Latency** — +1,500 ms in guideline search: Ask p95 +15%, search span p95 2.2 → 4.1 s (new `mcp <tool>`
  spans). Cost per consultation (draft + 3 questions, list price): $0.050 Gemini 3.5 Flash … $0.0019 Groq
  gpt-oss-20b. Docs: DPIA, vendor/BAA matrix, EU AI Act checklist, audit design, operations runbook,
  CONTRIBUTING, README (results, limitations, JEPA note), write-up draft. `just gate 6` + deliverables check.
- 2026-10-14: **Phase 4 (voice).** Speech keys added by you (Deepgram, Cartesia). Cascaded agent
  `voice/agent_cascaded.py` (LiveKit Agents 1.8.3 in its own uv project `voice/`: LiveKit pins
  opentelemetry < 1.45): Deepgram nova-3-medical STT, Silero VAD + LiveKit English end-of-turn model
  (`VOICE_TURN=semantic|vad`), barge-in on, Cartesia sonic-2 TTS; the pipeline's "LLM" is `/v1/ask`, so
  spoken answers are the de-identified, cited, guarded ones. `just voice` (console: microphone + speakers);
  smoke test through the API in the gate. **ASR** (`evals/reports/voice/asr_wer.md`, PriMock57 CC BY 4.0, 6
  consultations, both channels, 7,686 words): WER nova-3 0.119, + keyterms 0.121, nova-3-medical 0.112;
  medical-term errors 18 / 17 / 12 of 200 (keyterm boosting no gain; medical model adopted; small n).
  **Latency** (`evals/reports/voice/latency.md`, 30 golden questions spoken by Cartesia, streamed at real time):
  STT final p50 704 / p95 1,747 ms; Ask 1,864 / 18,493; TTS first byte 812 / 1,301; **TTFA 3,545 / 19,732 ms**
  (fast path 3,276 / 5,577) vs budget 1,500: not met; the bottleneck is Ask (non-streamed cited answer;
  agentic tail 6.8-22 s). End-of-utterance fired inside the question at 300 ms endpointing 1/30 times (a VAD
  cut-off). Measurement fixes on the way: negative STT latencies (Deepgram ended at a mid-question pause)
  now counted as early endpoints; a null byte and a per-process `hash()` cache key fixed in the script.
  **Speech-to-speech** (`evals/reports/voice/s2s_latency.md`, Gemini Live native audio): TTFA p50 3,493 /
  p95 6,137 ms: no faster than the cascaded fast path and without citations, guardrails or de-ID.
  ADR-0010 (LiveKit Agents; Pipecat compared on design, not built) and ADR-0011 (cascaded by default).
  **`just gate 4` PASS.** Not done: browser/WebRTC client (LiveKit server + token endpoint), the turn-
  detection false cut-off comparison semantic vs VAD on scripted pauses, AEC self-interruption test.
- 2026-10-18: **`just voice` fixed for live use** (branch `fix-voice-console`). Three faults the
  smoke test could not see, because it called `llm_node` directly: (1) the turn-detector and VAD
  model files were never downloaded (`just voice` now runs `download-files` first, into HF_HOME on D:);
  (2) LiveKit's default "adaptive" barge-in streams audio to LiveKit Cloud (401, no account; another
  vendor hearing raw audio), now local VAD interruption; (3) **LiveKit 1.8 skips the reply when the
  session has no LLM** (`agent_activity`: "skip response if no llm is set"), so spoken questions were
  transcribed and dropped with 0 API calls. A placeholder `AskApi` LLM fixes it; preemptive generation
  is off (each attempt would be a full `/v1/ask`, up to 3 per turn). The smoke test now runs a turn
  through an `AgentSession`; without the placeholder it makes 0 API calls. Verified by you live:
  question spoken, cited answer heard. Also fixed: the log `RedactionFilter` dropped record arguments,
  so every uvicorn access line raised "Logging error"; arguments are now scrubbed one by one and kept
  only when the joined message has nothing left to scrub (else the old behaviour), with tests for the
  access line and PHI split between template and argument. The running API picks it up at the next
  `just up rag` (rebuild); re-run `just eval leak` then.
- 2026-10-18: **Demo video** (`just demo-video`, `scripts/demo_video.py`; `docs/presentation/demo_video.md`):
  3 min 37 s, 1080p, recorded live from a hidden Chrome (Playwright 1.63.0 via `uv run --with`, not a
  project dependency; DevTools screencast + ffmpeg). Live: the voice steps (Deepgram nova-3-medical →
  `/v1/ask` → Cartesia), Ask in the UI (agentic path), Scribe (draft, wrong family name refused, approved
  write `DocumentReference/60565`), the audit log. Synthetic and labelled: the doctor's voice and the
  narrator (Cartesia), waits over 6 s compressed with the real time on screen. Voice turn in the run:
  time to first audio 5,745 ms (STT final 1,128, Ask 2,775, first audio byte 1,842). A first take showed
  the draft timer at "0.0 s" (it started after the narrator) and subtitles over the refusal; both fixed
  before the final take. Gap: Scribe from live consultation audio is not built (see Next).
- 2026-10-18: Review UI links in dark mode used the browser's default dark blue (unreadable on the dark
  cards); now the accent colour (#6ea8ff on #1d232c, ~6:1), checked in the browser on a live answer.
  `DEV_LOGIN=false` (you); stack rebuilt (`just up rag`, 11/11 healthy): `/v1/dev/login` 404, uvicorn
  access lines print again with the client IP scrubbed. Leak test on the new log filter, run `c4e02f4e`:
  **gate b PASS**, 0 leaks in 6 sinks, control 100%, 0 of 66 seed values reached the model.
- 2026-10-18: **Scribe from consultation audio** (closes the SPEC §14 gap "a live voice consultation
  through to an approved FHIR note"). `voice/scribe.py` (`just scribe <patient id>`, microphone or
  `--file`): Deepgram nova-3-medical live with diarization → turns by speaker → roles → `POST
  /v1/scribe/drafts` (de-ID per turn, note writer, guardrails). API: `GET /v1/drafts` (awaiting
  review, doctors only) and the transcript in `GET /v1/drafts/{id}`; UI: "Drafts awaiting review" in
  the Scribe tab. A standalone client, not a LiveKit worker: LiveKit's Deepgram plugin keeps one
  speaker per segment, and Scribe never speaks. `sounddevice` 0.5.6 in the `voice` group. **Eval**
  (`evals/voice/scribe_eval.py`, `evals/reports/voice/scribe_diarization.md`): PriMock57, 6
  consultations, both channels mixed to one stream: words to the right speaker **0.979** (rule v2;
  v1 0.783), purity 0.986, doctor found 6/6 (v1 4/6), WER 0.143 (0.112 on separate channels), drafts
  5/6 (108 turns failed: "no draft produced"; a 105-turn one failed in one run and passed in the
  next). Found and fixed on the way: (1) **the listener silently cut the end of a consultation**:
  it waited 30 s for the last results; words stopped at 322 of 458 s (WER looked like 0.41); now it
  waits for the server to close and refuses to draft a partial transcript; a "heard until" column
  guards it. (2) The first role rule ("first speaker of a 3+ word turn is the doctor") was fooled by
  a 3-word diarization fragment (attribution 0.33 and 0.42 on two consultations); v2 decides among
  main speakers (5%+ of the words) and labels fragments "unknown", designed after seeing v1 fail, so
  optimistic. (3) Live nova-3-medical wrote "five hundred milligrams": `numerals=true` added, and the
  dose guardrail now matches spoken units (milligrams, millimoles, millilitres, international units;
  its docstring had claimed this), red-team still 63/63. (4) Two synthetic TTS voices were not told
  apart by live or batch diarization, so the demo plays a PriMock57 consultation (real voices).
  Streaming a file faster than real time: Deepgram reads at ~2x anyway; pings now get 60 s.
  (5) **De-ID gap found in the demo draft**: a spoken date of birth ("21 12 at 1986", as Deepgram
  wrote it) and a spelled-out UK postcode ("N W 36 P Q") passed de-identification and reached the note
  writer (role-played PriMock57 values, but a breach of the rule all the same). New DATE patterns:
  spoken numeric dates with a four-digit year, "21st of December", day-month-year after a
  date-of-birth cue; new ZIP patterns: UK postcodes, and the spelled-out form after an address word.
  Unit tests for both and for look-alikes kept ("BP 140 90", "CD4 count 350", "B12"); `just eval
  privacy`: recall and over-redaction unchanged (0 of 80), p50 15.6 → 18.9 ms per snippet. The
  telemetry log filter reuses these patterns, so logs gain them too. Leak test after the rebuild:
  gate b PASS, 0 of 66 seed values reached the model; red-team 63/63; the live de-ID service turns
  the demo's sentence into "DATE_1 ... STREET_ADDRESS_1, ZIP_1". **Demo video re-recorded** (4 min
  51 s, `docs/presentation/demo_video.md`): Scribe now starts from the PriMock57 recording, and the
  draft shows the birth date and postcode as surrogates. `just lint` clean; `just test` 333 passed,
  3 skipped; deliverables 17/17. A dropped Deepgram connection (WinError 64, about 1 in 10 long file streams here)
  ends a listening session without a draft; not reconnected, because speaker numbers restart per
  connection.
- 2026-10-18: **Turn taking, barge-in and echo measured** (closes the Phase 4 "not done" items; SPEC
  §11 rows "Turn taking" and "Echo"). `voice/turn_eval.py` (`just voice-turns`, ~30 min; scoring in
  `voice/turn_metrics.py`, unit-tested): the production session (`agent_cascaded.build_session`, now
  shared with the agent) on LiveKit's own console audio classes, with the sound card simulated on a
  real-time clock and the console's WebRTC audio processing on the same path; the turn model runs in
  an inference process started as the worker does. Report `evals/reports/voice/turn_taking.md`:
  **cut off during a 0.7/1.2/2.0 s mid-sentence pause** VAD only 4/11/12 of 12, semantic 2/4/4,
  semantic with transcript punctuation off **0/1/0**; end of turn on whole questions p50 771 / 787 /
  905 ms, p95 904 / 857 / 3,107 ms (4 of 12 wait the 3 s maximum without punctuation). Cause found in
  the trace: Deepgram ended half-spoken sentences with "?" and the end-of-turn model took them as
  finished (the same 4 questions caused all 10 cut-offs). **ADR-0012 (proposed): punctuation off in
  the voice agent**. Barge-in: 12/12 interrupted; **the sound stops p50 616 / p95 629 ms** after the
  user starts (LiveKit pauses, then drops the answer at ~2.3 s once confirmed; inside the 3 s AEC
  warm-up the interruption is ignored). Echo back into the microphone (linear, -12/-24 dB):
  self-interruption 0/8 replies with the console's echo cancellation, 8/8 without (and the echo is
  transcribed as user turns). Found on the way: (1) synthesizing speech inside a session blocked the
  event loop > 60 s, so the turn model's process was declared crashed and every semantic prediction
  failed: speech is now prepared first and the eval stops if that process dies; (2) the first semantic
  inference is slow, so each session starts with one unscored question; (3) barge-in first looked like
  2.3 s because the clear, not the pause, was timed; (4) ADR-0010 and the agent's docstring said
  console echo cancellation came from the OS: it is LiveKit's console (WebRTC APM); corrected.
  **Cartesia's free-tier credit ran out on 2026-10-18 (HTTP 402)**: the eval uses Deepgram Aura voices;
  `just voice` speaks with Cartesia, so spoken answers fail until the credit resets.
- 2026-10-19: **The voice agent speaks with Deepgram Aura-2** (`aura-2-orpheus-en`; you asked;
  ADR-0013, proposed). The LiveKit Cartesia plugin is removed from `voice/` (lock: only that package
  left). The voice smoke test (gate 4) now also synthesizes the answer with the production voice
  (6.6 s of audio), so a TTS vendor that stops working fails the gate. The latency eval moved to Aura
  for the answer and to nova-3-medical (production; it measured nova-3 before); question audio is the
  same cached Cartesia speech. **Re-measured** (`evals/reports/voice/latency.md`, 29/30 answered):
  STT final p50 730 / p95 1,910 ms, Ask 2,113 / 4,856, TTS first byte 1,413 / 1,550 (Cartesia was
  812 / 1,301), **TTFA 4,296 / 7,093 ms** (budget 1,500: not met; Ask's agentic tail was shorter than
  on 2026-10-14). The demo script uses Aura for the narrator, the doctor's question and the answer.
  **Found: the one failed turn** (502 after 140 s) had every cloud fallback rate-limited and then the
  local model timed out: the router's 60 s timeout is shorter than a cold Ollama load (~75 s). The gate
  never saw this because its previous test leaves the model warm. Fixed: `timeout: 180` for
  `clinscribe-fallback-local` (confirmed in LiteLLM's model info); the cloud-down gate test now unloads
  the model first and uses a 300 s client. **Not run yet: C: had 0.18 GB free** (a model load grows the
  C: page file by ~1 GB; this machine blue-screened once at low C: space), so the cold-start test and
  the demo re-recording wait for space.
- 2026-10-19: **C: space recovered** (you asked): regenerable caches moved, not deleted, to
  `D:\devcache\c-cleanup-quarantine\2026-10-19\` (15.6 GB: NVIDIA DirectX shader cache 8.9 GB, Yarn
  package cache 6.3 GB, crash dumps 0.2 GB, temp files older than 2 days 0.2 GB; files in use were
  skipped); C: 0.18 → 18.1 GB free (11.5 GB after Docker started and the model loaded: page file).
  Programs, browser profiles and app data untouched. Delete the quarantine folder when nothing
  misses it. **Cold-start failover test PASS**: model unloaded, every cloud provider down, the turn
  served by the local model in 126 s (it timed out at 60 s before the fix). PR #25 opened from the
  built-in browser (CI green); merging there is blocked by the browser (`ERR_BLOCKED_BY_CLIENT` on
  GitHub's merge box), so the merge click is yours.
- 2026-10-19: **A refused write for wrong identifiers keeps the draft open** (was: the draft ended, so
  a typo in the family name meant drafting again). `commit` returns to the doctor's review on
  fhir-mcp's identifier refusal only (`agents.schemas.IDENTITY_MISMATCH`, shared with fhir-mcp), at
  most 3 attempts per draft (`MAX_IDENTITY_ATTEMPTS`: more would allow guessing birth dates); every
  attempt is still refused and audited by fhir-mcp; any other refusal (bad token, wrong resource)
  ends the draft as before. The review payload carries the refusal and the attempts left; the API
  answers `awaiting_review` + `attempts_left`; the UI keeps the identifier fields open and shows the
  reason. Unit tests +3 (corrected attempt writes; cap at 3; other refusals end), graph tests 14/14,
  red-team 63/63. **Demo video re-recorded** with the Deepgram Aura voices and this flow (4 min 50 s;
  the narration was tightened because the Aura narrator reads at ~125 words per minute and the first
  take ran 5 min 31 s): wrong family name refused, the draft stays open ("2 attempts left"), the
  name is corrected, `Saved to FHIR: DocumentReference/62852`. Upload it in place of the earlier one.

- 2026-10-19: **LoRA de-ID tagger, round 1** (you trained it on Colab; the install cell first failed on
  `seqeval`, which no longer builds there: the notebook now computes the entity scores itself, equal
  to seqeval on 300 random cases). `evals/privacy/lora_eval.py` compares spaCy, the tagger, and both,
  through the same analyzer (`build_analyzer(spacy_ner=..., extra=...)`). The tagger's training
  phrasings had been written after seeing held-out v1's misses, so new sets were frozen before any
  model ran: held-out v2 and v3 (names/places) and PHI-free v2 (40 sentences). **Result
  (`evals/reports/privacy/deid_lora_round1.md`): tagger recall 1.000 names and places on held-out v2
  (spaCy 0.991 / 0.814), 0.978 / 1.000 on v3 (spaCy 1.000 / 0.840), but it altered 15/80 and 13/40
  PHI-free sentences (spaCy 0 and 3)**: it tags capitalised sentence starts, acronyms and ward names,
  because 9 of 12 round-1 templates start with a name and none was PHI-free. **Not adopted; the
  service keeps spaCy.** Also found: spaCy alters 3 of the 40 new PHI-free sentences ("FEV1" and
  "Bay 2" as places, "Sleeps"): its 0/80 was on the set its rules were tuned on. Not tuned now (that
  would spend the new set). Round 2 data (`finetune/make_dataset.py`, default): 12 templates with
  names away from the start, ~40% PHI-free clinical sentences from parts; fair sets for round 2 are
  held-out v3 and PHI-free v2. Base model download: `distilbert-base-cased` (~260 MB, HF cache on D:);
  `peft==0.21.2` only via `uv run --with` (not a project dependency unless adopted).

- 2026-10-24: **LoRA de-ID tagger, round 2: adopted behind `DEID_NER=tagger` (ADR-0014, proposed).**
  You trained round 2 on Colab. On the sets frozen before it was trained
  (`evals/reports/privacy/deid_lora_round2.md`): names 90/90 and places 50/50 (spaCy 90/90 and
  42/50), PHI-free sentences altered 1 of 40 (spaCy 3); the union of both models adds no recall and
  keeps spaCy's over-redaction (4 of 40). `finetune/merge.py` merges the adapter into one model
  (`data/finetune/deid_ner_tagger/`, SHA-256 in the ADR), so the service needs no peft;
  `privacy/deid/tagger.py` is a Presidio recogniser that replaces spaCy's NER (context cues, the
  clinical-term filter and every structured pattern unchanged). The local `.env` now runs it
  (`DEID_NER=tagger` + the rag image and a 3.5 GiB limit through three Compose variables); code, CI
  and a fresh clone default to spaCy (the model lives in git-ignored `data/`). Found and fixed
  before adoption: (1) a span took the sentence's full stop ("Denver."), (2) a 200-word window past
  the 512-token limit would have left the words after the cut unseen and labelled "O" (a leak); the
  window now continues at the first word left out, tested with a fake tokenizer so CI covers it
  without the model, and the old logic fails that test. As the configured service: `just eval
  privacy` gate PASS (seeded 1.000 / 1.000, over-redaction 0 of 80, held-out v1 names 0.991 and
  places 1.000 vs spaCy 0.973 / 0.850), p50 52 / p95 82 ms per snippet (spaCy ~19 ms). **Leak test
  run `8697df2f`: gate b PASS**, 0 of 66 seed values reached the model. **Load** (warm, back to back:
  tagger, spaCy, tagger): about 14% less throughput (5.3 → 4.1-4.9 req/s), +0.3-1.8 s at p50; de-ID
  2.1-2.3 GiB vs 1.1; stack 5.9 GiB (`evals/reports/load/load_test.md`). The first load run straight
  after a cold start looked much worse (p95 8.6 s at 10 sessions), which warm runs did not repeat.
  A first attempt on 2026-10-19 stopped when the internet dropped (`uv run` re-checks the spaCy wheel
  URL; `UV_NO_SYNC=1` avoids it).

- 2026-10-24: **Re-identification for the doctor's screen and the approved record** (ADR-0015,
  proposed). SPEC §8 asks for it; it existed only as a library function, and PROGRESS had listed a
  doctor-only `/reidentify` as done in Phase 3 (corrected above). Doctors therefore reviewed
  "PERSON_1 ... LOCATION_1", and approved notes were saved to FHIR in surrogate form (dates lost,
  readable only through the mapping). Now: `POST /reidentify` on the de-ID service, callable only
  with `DEID_REIDENTIFY_KEY` (held by the API and the de-ID service; 403 otherwise, checked live);
  the API serves originals to doctors on request (`?identified=true` on Ask, draft creation and the
  draft view) and audits each disclosure as `phi.reidentify` (counts only); on approval it
  re-identifies the note and signs the token over that exact resource, so the record holds what the
  doctor read; edits typed on the identified view are de-identified again before they re-enter the
  graph, so edit pairs stay PHI-free. UI: originals by default, "Show what the AI saw" toggle
  (surrogates, read-only). Voice answers stay surrogate-only (the TTS vendor would receive
  originals). Checked in the browser against the live stack: a synthetic name and town shown to the
  doctor, `LOCATION_1` / `PERSON_1` in the AI view, the doctor's edit saved as
  `DocumentReference/63553` with the real name, `phi.reidentify` in the audit log; then 0
  occurrences of either value in 70 MB of container logs and the trace export. Tests: unit 8
  (route key checks, client, API flow with a scripted model), live 3/3 (new: model sees a
  surrogate, doctor the name, record the doctor's words, edit pair none).

- 2026-10-24: **Durable drafts** (ADR-0016, proposed). Drafts awaiting review lived in the API's
  memory, so every restart (each `just up` rebuild) silently dropped them. Now LangGraph's Postgres
  checkpointer (`langgraph-checkpoint-postgres` 3.1.2, the newest that fits the pinned
  `langgraph-checkpoint` 4.2.0; `uv lock` added it and `psycopg-pool`, nothing else moved) plus a
  `drafts` table (migration 003; `app` may insert/update, not delete). `just migrate` creates
  LangGraph's tables as the owner and grants `app` DML on them. PHI kept out of the database: the
  identifiers and the re-identified resource now reach the commit node as LangGraph run context
  (`WriteContext`), never checkpointed (a probe first showed the context stays out of all three
  checkpoint tables); the resume payload carries only the decision and the token. Ask uses a graph
  without a checkpointer. When a draft ends, its checkpoints are deleted and `drafts` keeps the
  outcome. Tests: unit 5 (lifecycle through a simulated restart; identifiers never checkpointed, with
  a positive control; no write without identifiers), integration 2 on the real Postgres (another
  process and pool resume the draft; the checkpoint rows hold the draft text but not the identifiers;
  no rows left after the end), live 4/4 (new: a draft made before `docker compose restart api` is
  listed and approved after it).
- 2026-10-24: **Real defect found: FastAPI's own telemetry bypassed the app-level span redaction**
  (postmortem 0004). A metrics-export 404 in the API log (nothing in ClinScribe exports metrics)
  led to FastAPI 0.142's OpenTelemetry support, on by default: before the lifespan it installs a
  global tracer provider with a plain OTLP exporter, so `configure_tracing`'s redacting provider
  was refused (a warning at every start since Phase 1). In the API and de-ID service only the
  collector's redaction layer was active for 19 days; it held (every leak test 0 leaks). FastAPI's
  own spans were ~80% of exported spans (1,072 of 1,340 in a sample), likely a large part of the
  Langfuse quota use. Fix: `FASTAPI_TELEMETRY` (tracing, metrics, logs, auto-configure off) in both
  apps, and `configure_tracing` now fails closed if another provider is installed. Verified on the
  rebuilt stack: the provider wraps the OTLP exporter in `RedactingSpanExporter`, no override
  warnings or metric errors, no `fastapi`-scope spans after the rebuild. Tests in a fresh
  interpreter with a control (FastAPI's defaults do install all three providers).

- 2026-10-25: **Runtime citation support check: measured, not adopted** (ADR-0017, proposed). SPEC §6
  asks for a check that each cited chunk supports its sentence (SPEC §1: citation precision ≥ 0.95);
  only citation existence and dose sources were checked at runtime. Offline, with the Phase 2 judge's
  362 rated links as labels (307 supports, 47 partial, 8 no; no LLM calls,
  `evals/rag/citation_support.py`): three Apache-2.0 NLI cross-encoders, on whole chunks and on
  their best 2-sentence window, two policies, threshold by 2-fold cross-validation over questions.
  AUC 0.58–0.75; on the chosen pipeline, reaching 0.89–0.97 precision empties 19–29 of 49 answers,
  and the safe policy (keep each sentence's best citation) gains only 0.02–0.05 while dropping
  16–25% of the good citations, at 0.4–1.7 s CPU per answer. Not built; the gap is now stated in
  the README (0.875 vs 0.95). Then a generator trial, `prompts/experiments/answer_cited_v2.yaml`
  (one passage per sentence; `answer_eval --prompt ... --name ...` keeps its rows apart), with the
  adoption rule written down first (ADR-0017: precision better, correctness non-inferior at −0.05,
  correct abstentions not lower). Result, 60 of 60: citation precision 0.865 → 0.963 (+0.098
  [+0.041, +0.158]), correctness 0.910 → 0.870 (−0.040 [−0.110, +0.020]), correct abstentions
  10/10 → 9/10: **not adopted**. The abstention it missed was a wrong-drug answer: mazdutide (not in
  the corpus) answered from the Ozempic (semaglutide) label, every sentence faithful to its source.

- 2026-10-25: **Question-subject grounding** (ADR-0018, proposed), after the v2 trial's wrong-drug
  answer (mazdutide answered from the semaglutide label, every sentence faithful to its source).
  Two deterministic checks in `retrieval/grounding.py`, served by a new guidelines-mcp tool
  `check_grounding` (re-de-identifies the question; de-ID surrogates never count): (a) a question
  word no source uses and that is not common English (spaCy vectors) nor a UK/US spelling of a
  corpus word ends the question abstained in the router, before search and models, and the API,
  UI and voice agent name the term; (b) a drug the question names (DDInter + RxNorm lexicon) that
  no cited source names is a guardrail violation (one retry, then the safe reply). Measured offline
  first (`evals/rag/drug_grounding.py`): (a) blocks 0 of 209 answerable golden questions and
  catches 25 of 26 unanswerable (optimistic: those were built around absent drugs; the spelling
  fold was added after seeing "nebulised"); (b) blocks none of 185 stored answers. Cost: p50 109 /
  p95 214 ms per check call, two per answered question. Red-team 65/65 with 2 wrong-drug cases
  (control 23/65: both fail with the checks off); live 5/5 (new: the mazdutide question abstains
  in 0.7 s with no model call).

- 2026-10-25: **Gemini implicit prompt caching measured** (SPEC §7; it had never been): from the
  gateway's spend log (`evals/llmops/prompt_cache.py`, `evals/reports/llmops/prompt_cache.md`),
  0 cached tokens in all 262 successful Gemini calls so far (50 with prompts of 1,024+ tokens, the
  size Gemini needs), and 0 of 12 in a controlled check: one identical 2,459-token prefix, 8 of
  the calls repeats to a model already called within two minutes, all four Gemini models. So
  implicit caching gives this free-tier set-up through LiteLLM no saving; the cause (free tier, or
  how the system prompt reaches Gemini) is not separated. The gateway client now keeps the
  provider's `cached_tokens` (`Completion.cached_input_tokens`). Found on the way: a no-log call
  (`GatewayClient(trace=False)`, used by bulk evaluations) gets no spend-log row at all, which the
  2026-10-13 entry had said otherwise; the cost report uses only app traffic, so it is unaffected.
- 2026-10-25: **Note quality vs the reference note** (SPEC §11 "Notes", never measured; only schema
  validity had been): `evals/agents/note_quality.py` with a rubric judge in two calls per draft
  (coverage of the reference's important facts, critical ones separately; support of each
  statement by the transcript turns it cites), controls (the reference as the draft; the draft
  without assessment and plan). Built to fit Groq's free 8k tokens per minute for the judge
  (prompt + max_tokens; `reasoning_effort: low`, now a gateway-client option). The judge's daily
  budget ran out after today's other runs; a background job resumes it every 25 minutes
  (results cached). Partial: D2N075 recall 0.88, critical 0.93, 2 of 25 statements unsupported.

- 2026-10-26: **Browser voice over WebRTC** (ADR-0019, proposed; SPEC §4 "audio travels over
  WebRTC through a LiveKit server", until now console mode only). Self-hosted LiveKit server
  (`livekit/livekit-server:v1.13.9`, profile `voice`, ports on 127.0.0.1, media on one UDP port,
  69 MiB); `POST /v1/voice/token` (doctors only, audited as `voice.session`, HS256 room token
  written directly); the agent worker (`just voice dev|start`) joins each room and sends every cited
  answer (sentences, citations, source titles and links) on the room's data channel; the review UI's
  Voice tab (`livekit-client` 2.22.4, lazy-loaded) plays the agent, shows the live transcript and
  the citations. **End to end without a browser** (`voice/webrtc_check.py`, `just voice-webrtc`,
  `evals/reports/voice/webrtc.md`): a Python LiveKit client as the doctor, 10 recorded questions:
  agent joined in 1.7 s, 9 spoken replies, 8 cited answers on the data channel, time to first audio
  at the client p50 6.8 / p95 16.9 s (in-process measurement 4.3 / 7.1 s leaves out the end-of-turn
  wait and the network). Two things it found in its own first runs: my listener died silently on a
  memoryview cast (fixed, failures now printed), and one recorded question was split into two
  turns when speech recognition dropped "ARBs" (counted as a split, kept out of the timing). In the
  browser pane: token, connection, agent present, greeting transcript, live agent audio track; the
  pane blocks microphones, so a spoken browser question was not tried. One machine only (127.0.0.1,
  no TURN, no TLS); the worker uses the demo doctor's API token. Stack with voice 5.55 GiB.

- 2026-10-26: **Vite 8.3.1 → 8.3.3** (review UI dev server). `npm audit` reported six advisories
  for Vite `>=8.3.0 <=8.3.2`, the highest GHSA-587h-7wmj-h5pm (launch-editor, Windows), plus
  cross-origin script execution through custom middleware and files outside `server.fs` served or
  partly exposed. 8.3.3 is the lowest fixed release and 20 days old (8.3.5, which `npm audit fix
  --force` proposed, was 5 days old); only Vite moved in the lock (rolldown 1.2.13 already met its
  new range). `npm audit`: 0 vulnerabilities. Built, and the dev server (still on 127.0.0.1, `/v1`
  proxy unchanged) served the Ask tab, an authenticated API call through the proxy and the Voice
  tab's lazy chunk and LiveKit connection, with no console errors.

- 2026-10-26: **Voice questions are audited as the doctor in the room** (ADR-0019 update; SPEC §2
  story 5, §8 audit). The worker used to ask `/v1/ask` with the demo doctor's token, so every
  spoken question was recorded as `dr-demo` whoever was in the room. Now the worker holds a
  service key (`VOICE_AGENT_KEY`, `just gen-keys`) and, when a doctor joins, gets a 30-minute API
  token for that doctor from `POST /v1/voice/delegate`: only with the key (constant-time compare),
  only for a doctor, only for a room the API issued to that doctor (`clinscribe-<user>-<8 hex>`),
  audited as `voice.delegate`. LiveKit already checked the participant against the room token the
  API signed. Fails closed: on a refusal the agent says it cannot confirm who is asking and sends
  nothing to the API; console mode keeps the demo doctor. Considered and not chosen: the browser
  passing its own token over the data channel (readable by every participant), an agent role
  (the log would name the agent). **Live** (`just voice-webrtc dr-second`, which now reads the
  audit log with an admin token): 10 questions, 10 cited answers, audit `ask by dr-second` ×10 and
  `voice.delegate by dr-second` ×1, none as `dr-demo`; time to first audio p50 6.7 / p95 7.9 s.
  A worker started with a wrong key: 403, 0 of 2 questions answered, no `ask` row. Unit tests 11
  (`tests/unit/test_voice_delegate.py`); voice smoke test passes (console path). Audit design and
  the runbook (start-up, key rotation) updated.

- 2026-10-26: **Note quality vs the reference note: complete** (SPEC §11 "Notes"; started
  2026-10-25). 8 ACI-Bench consultations, the current de-ID and note writer, rubric judge (Groq
  gpt-oss-120b, two calls per draft, cached; 11 resumptions over the free tier's daily limit).
  First full run: fact recall 0.83, critical-fact recall 0.87 (medications and doses, allergies,
  abnormal results, the plan), statements supported by their cited turns 0.97 (4 of 167 not),
  sections fit 1.00; controls behave (the reference as the draft 1.00 / 1.00; the draft without
  assessment and plan 0.59 / 0.49). The report now lists each missed critical fact and each
  unsupported statement, and that list found a guardrail defect (next entry): two plans had lost a
  dose the doctor had said in words. After the fix: **fact recall 0.85, critical 0.92, 3 of 171
  unsupported** (`evals/reports/agents/note_quality.md`). Remaining misses: D2N072's plan is vague
  ("ordered discussed medications and procedures", the note writer's first and only attempt; the
  splint and Motrin 600 mg are missing), D2N075 leaves out the reason for the visit. One judge, no
  clinician check, no intervals over 8 consultations: indicative.
- 2026-10-26: **Dose rule reads doses in words** (guardrails v2, ADR-0020, proposed). The dose rule
  read only digits, so "oxycodone five milligrams" in the consultation did not source the note's
  "5 mg": D2N085's draft lost the prescription, and in D2N077 ("fifty milligrams of ultram") the
  flag forced a retry that dropped the brace from the plan. The other way round, "ten milligrams"
  in an answer was invisible to the rule. Now number words become digits where a dose then reads
  ("two point five mg", "five to ten milligrams"; "two 500 mg tablets" stays a count), on both the
  sentence and its sources, and a range needs "-", "to" or "–". Checked with no model calls:
  red-team 67/67 with two new word-dose cases; with v1 rules in the system exactly those two fail
  (on note-07 v1 removed the correct "500 mg" statement and kept the invented increase); corpus:
  2 dose pairs gained, 109 dropped in 55 chunks, all inspected ones table artefacts (row numbers,
  days, trial arm sizes, weights) that could have "supported" an invented dose; 325 stored answer
  sentences: no verdict change. D2N087's flag was correct (wrong turn cited); its retry dropped the
  dose instead of fixing the citation (noted, not changed). Unit tests +4.

- 2026-10-26: **HL7 v2 ORU^R01 → FHIR Observations** (ADR-0021, proposed; SPEC §8 "one ORU^R01
  lab message is converted into FHIR Observations", §13 "FHIR R4, HL7", never built). A small
  reader for MSH, PID, OBR and OBX (`agents/lab/hl7.py`, no dependency: separators and escapes from
  MSH, carriage-return / newline / MLLP framing) produces Lab mode's `LabReport`, so the message
  goes through the same review as a PDF: preliminary Observations, identity check, the doctor's
  confirmation, one approved write per value. Only numeric, LOINC-coded, known tests in the
  expected unit with status F or C are mapped; anything else is listed for the doctor with the
  reason. The identity check gains the MRN (PID-3) for messages. `parse_lab_report` and
  `POST /v1/lab/parse` take `pdf_base64` or `hl7_message`; the audit row records the format.
  **Measured** (`just eval lab`, `evals/reports/lab/hl7_oru.md`): 20 Synthea patients, 155/155
  results with the right LOINC code, value, unit and flag (16 abnormal), identity 20/20,
  wrong-patient control 20/20 (each caught by the MRN alone), newline and MLLP framing read the
  same 20/20. Integration 3 new (message → confirm → final Observations in HAPI; another
  patient's message refused 409; both or neither report 422); unit 14. Limits: one synthetic
  sender written by this project; no MLLP listener, ACKs, local codes or Z-segments. Found on the
  way: README and the Phase 5 table said 162/162 for the PDF evaluation; its report says 155/155
  since the gate re-run (the lab integration test writes two Observations that became patient
  1617's latest panel, 2 values instead of 9); corrected.

- 2026-10-26: **Retention limits and GDPR erasure** (ADR-0022, proposed; SPEC §8 "retention limits,
  erasure endpoint", listed as gaps in the DPIA). `scripts/retention.py`: `just retention` (drafts
  nobody reviewed in 14 days end as "expired" and their saved state goes; an encounter's encrypted
  de-ID mapping, the only place originals are kept, goes 30 days after it last gained a value,
  except while its draft waits; `config/retention.yaml`) and `just erase <patient> --request
  <ticket> --by <admin>` (ends the patient's waiting drafts as "erased", deletes the mappings of
  every encounter their drafts used). Dry run by default; an applied run writes one audit row
  (`retention.run` / `gdpr.erasure`, counts only) in the same transaction as the deletions. A new
  `retention` login (created by `just migrate`, password from `just gen-keys`) may delete mappings
  and checkpoints, end drafts and append to the audit log; the API's `app` login still cannot
  delete a mapping, which is why this is a command and not an API endpoint. Mappings go as whole
  encounters, under the de-ID service's per-encounter lock, re-checked for idleness (surrogate
  numbers count an encounter's rows, so a partial delete would reuse a number). Kept, with the
  basis in the DPIA: audit log, drafts list, FHIR record. Found on the way: the voice agent sent
  every question as encounter `voice-session`, one mapping shared by all voice sessions that never
  went idle; now one encounter per session. Integration 8 (stale vs waiting vs ended drafts; an
  encounter used again after the plan keeps its mapping; erasure leaves another patient untouched
  and nothing re-identifiable; a failed audit write rolls the deletions back; free-text request,
  non-admin and bad id refused; each login's limits); removing either safeguard fails a test.

- 2026-10-26: **Grafana dashboards** (ADR-0023, proposed; SPEC §7 "p50/p95 latency per stage,
  error rate, failover count, cost per consultation", never built). Compose profile `obs`
  (`just up obs`, then `just migrate`): Prometheus `v3.13.4` (15 days) scrapes span metrics that
  the collector's `spanmetrics` connector makes from the redacted spans; Grafana `12.4.12` (local,
  no sign-up, no usage reporting) has one provisioned dashboard, "ClinScribe operations", and
  reads the gateway's spend log through `grafana_reader` (SELECT on ten columns of one table, no
  request or response content). The gateway client now tags every call with the alias asked for
  and, inside `for_encounter`, the encounter (spend-log metadata, outside the replay-cache key; the
  API sets it around every graph run): a failover is a call served by another alias than the one
  asked for (answers ask for `clinscribe-fallback-groq` by design, so "served by a fallback alias"
  would count every answer). Found and fixed on the way: health checks were most spans and went
  to Langfuse (now untraced); API spans were named by raw path (now by route template; 5xx marked
  as errors); the collector's redaction removed `service.name` from every span, Langfuse
  included (now allow-listed in both layers); the trace file had grown to 45 MB with no rotation
  (now 100 MB x 3 backups, 30 days; the leak test scans the backups). **Checked live** with one
  synthetic consultation (draft + 3 questions) and one draft with the primary down: all 18 panel
  queries run through Grafana's query API; the failover counted (asked `clinscribe-default`,
  served by `clinscribe-fallback-groq`); cost per encounter at list price, Ask ~$0.0002, the
  Gemini draft $0.0046. Two dashboard faults found by looking at it: the per-stage table used
  `increase()`, which cannot count a series' first observations, so the 117 s draft vanished
  from p95 (now cumulative counters, "since the collector started"; p95 114 s, bucket estimate);
  daily cost fell outside short ranges (own 30-day window). Grafana 13.2.3 was tried first and
  dropped: plugins loaded after start (panels failed on early loads) and 471 vs 137 MiB. **Leak
  test** with a new sink, every Prometheus label value: gate b PASS, 0 leaks, 0 of 66 seed values
  reached the model. Unit 8, integration 4 (`CLINSCRIBE_REQUIRE_OBS=1` to require the profile).
  Stack with every profile 6.08 GB.

- 2026-10-27: **Arize Phoenix tried against Langfuse Cloud** (ADR-0024, proposed; SPEC §7 "Phoenix is
  tried once and compared in an ADR"). `just phoenix on` layers `docker-compose.phoenix.yml` over
  the stack: Phoenix `20.21.1` (127.0.0.1:6006, telemetry off) and a merged collector config that
  sends the same redacted spans to the file, Langfuse and Phoenix; `just phoenix off` restores it.
  **Measured** (`evals/llmops/tracing_compare.py`, `evals/reports/llmops/tracing_backends.md`; one
  synthetic consultation, real models): Phoenix stored 71 of the 71 spans of the 5 traces the file
  holds (70 of 70 in a second run), trees intact; Langfuse 0 (ingestion still suspended by the free
  tier). Phoenix reads our
  OpenTelemetry GenAI attributes into its own model and token fields with no instrumentation
  change; its cost column is $0 (it does not know LiteLLM's names); 448–599 MiB, 1.42 GB image,
  ~60 s first start and 29 s restart, no login by default. Decision: Langfuse stays configured,
  Phoenix is the optional local backend. **Leak test** with Phoenix as a new sink: gate b PASS,
  0 leaks in 8 sinks (69,230 bytes of Phoenix spans), 0 of 66 seed values reached the model.
  Found and fixed on the way: clinical audit rows never
  recorded the trace id (only the dev pipeline did), so an operator could not go from an audit row
  to its trace (SPEC §2 stories 5 and 6); every row now carries its request's trace id. Unit +2.

- 2026-10-27: **GitGuardian's four "Generic Password" findings on PR #36 checked: false positives.**
  None of the 30 secret-named values in `.env` appears in any commit on any branch. The flagged
  lines were a connection-string template (`config/db.py`), two `${...:?run just gen-keys}`
  substitutions (`docker-compose.yml`) and a `LOGIN PASSWORD {}` SQL template filled with a
  quoted literal (`scripts/migrate.py`). Two changes from it: connection strings are now built
  with psycopg's `make_conninfo`, which quotes values (the f-string broke on a password with a
  space: "missing '=' after 'words'"); and `tests/unit/test_secrets.py` fails if any secret value
  from `.env` is in a tracked file (keys and files reported, never values; negative control: a
  planted value was caught). The GitGuardian incidents still need marking as false positives in
  its dashboard (yours).

- 2026-10-27: **GDPR access requests** (Art. 15; ADR-0022 update; the DPIA's last data-subject-
  rights gap). `just access-report <patient> --request <ticket> --by <admin>` writes what
  ClinScribe holds about one patient to `.artifacts/subject-access/` (git-ignored, holds PHI, never
  printed): the drafts list, a waiting draft's transcript and note re-identified from the mapping,
  the mapping's originals, the audit rows naming the patient, their drafts or encounters, and the
  purposes, recipients and retention limits; the clinical record is pointed to the EHR. Audited as
  `gdpr.access` (ticket id and counts only), before the file is written. Same login and request
  checks as erasure. Integration +1 on the real Postgres (a graph-made draft's surrogate comes back
  as the original; another patient's data absent; the audit row holds counts, not data; repeatable
  across runs, since the audit log keeps every earlier row), unit +1.

- 2026-10-27: **Fast path vs agentic loop, and the router** (SPEC §6 "judged by how often it picks
  the cheaper path without losing answer quality"; ablation step 7; closes Phase 3 task 5).
  `evals/agents/router_eval.py`: 39 golden questions (all 19 answerable interaction questions,
  10 other questions the router sends agentic, 10 it sends fast) through the real Ask graph
  forced down each path (production retrieval, drug facts, models, guardrails; `Agents` now takes
  a routing rule, production default unchanged), every answer judged by `judge_citations`; one
  run, 78 answers, 0 judge errors. **Correctness does not separate the paths** (fast 0.833,
  agentic 0.833, router 0.859; every interval spans 0). **The agentic loop raises faithfulness**
  +0.103 [+0.015, +0.206] (n 34; grading drops passages before the answer is written); citation
  precision +0.082 [-0.029, +0.201]. **The router against always-agentic**: correctness +0.026
  [-0.026, +0.090], faithfulness -0.038 [-0.117, +0.019], neither shown worse; on all 209
  answerable golden questions it sends 17% agentic, so about 1.3 model calls and 2,820 tokens per
  question against 2.4 and 5,125, and the agentic median is 7.2 s against 1.9 s (it matters for
  voice). Reading: keep the router; the faithfulness gain is real but not enough here to pay
  double cost and four times the wait for every question. Caveats: small n, one judge, the
  router's interaction cues were widened on this golden set. Unit +1.

## Next
- **You: try the Voice tab with your microphone** (`just up voice`, `just voice dev`, review UI → voice)
  and **review ADR-0019** (browser voice); also **ADR-0018** (question-subject grounding), **ADR-0017** (citation support check not
  adopted), **ADR-0016** (durable drafts) and
  **postmortem 0004** (FastAPI telemetry bypassed the app-level span redaction), then ADR-0015 and 0014.
- **You: open the PR for `router-eval`** (the built-in browser is signed out of GitHub).
- **You: review ADR-0024** (Phoenix trial), ADR-0023 (dashboards), ADR-0022 (retention, erasure and
  access), ADR-0021 (HL7 v2) and ADR-0020 (dose rule v2). Mark GitGuardian's four findings on PR
  #36 as false positives in its dashboard. Grafana: `just up obs`, then http://127.0.0.1:3000 (user
  `admin`, `GRAFANA_ADMIN_PASSWORD` in `.env`). Schedule `just retention --apply` daily if the
  stack stays up.
- **You: review ADR-0012** (turn detection: punctuation off) **and ADR-0013** (Deepgram Aura TTS).
- **You (or a clinician reviewer): fill `evals/golden/review/review_v1.csv`** (49 rows; open in Excel;
  verdict ok / fix / reject, notes, reviewer, date), then I apply fixes and close task 3.
- **You: review ADR-0007** (vector store), the ADR-0006 BM25 update, and ADR-0008 / ADR-0009 (Phase 3).
- **You: watch `.artifacts/demo/clinscribe_demo.mp4`, upload it (YouTube, unlisted) and send me the
  link** for `docs/presentation/demo_video.md`.
- Optional: try `just scribe 1617` with two people at one microphone (the eval mixed two close-talk
  microphones; a room is harder).
- **Phase 2 closes when `just gate 2` passes:** only the golden review sheet (first item) is missing.
  Optional: a throwaway PR that breaks the BM25 tokenizer, to see CI go red on GitHub (shown locally).
- You (recommended after the 0x1A blue screen): run Windows Memory Diagnostic (`mdsched.exe`).

## Blockers

- **Langfuse Cloud ingestion suspended (2026-10-10; non-blocking since 2026-10-13).** HTTP 403 "Usage
  threshold exceeded" on `/api/public/otel/v1/traces`; the collector drops Langfuse batches (local file
  export unaffected, so the PHI leak scan of the file sink still works). The Langfuse delivery test skips
  with that reason until the monthly reset. Cause: ~8k contextual-prefix calls (task 7) plus ~500 answer/judge calls (task 10),
  each traced with several observations.

- **C: space (resolved 2026-10-06).** Moved the Ubuntu WSL distro to `D:\WSL\Ubuntu` (`wsl --manage --move`,
  10 GB) and VS Code extensions to `D:\devcache\vscode\extensions` (junction at the old path, 59,066 files
  verified): C: went from 3.6 to 16.0 GB free, so the system-managed page file can grow safely. WSL cap back to
  10 GB (ADR-0003). Kept: local model `num_ctx 2048` + `keep_alive 30s`, local-model check in the Phase 5 gate.
- LiteLLM was OOM-killed (`exit 137`) once during a start-up under host memory pressure; it ran at 520–630 MB of
  its 1 GB limit otherwise and was healthy in the passing gate run. Watch for repeats.
- All project caches are on D: (uv, Python, tools, Ollama, HF, npm, Docker data, WSL swap, pytest temp);
  `just doctor` warns if any moves back to C:.
- Network: IPv6 connections from this PC hang until timeout (root cause of the slow `localhost` DB
  connections, Ollama pull failures and many "connection reset" retries). IPv4 works. Recommended (you, a
  Windows system setting, admin + reboot): prefer IPv4 with
  `reg add HKLM\SYSTEM\CurrentControlSet\Services\Tcpip6\Parameters /v DisabledComponents /t REG_DWORD /d 0x20 /f`.
- The machine PATH lacks `C:\Windows\System32\WindowsPowerShell\v1.0`; the justfile uses the full path.

## Open questions

- ~~Pending drafts live in LangGraph's in-memory checkpointer~~: resolved 2026-10-24 (ADR-0016), Postgres
  checkpoints without PHI; lab results awaiting confirmation are still in memory.
- ~~Drafts and answers are shown in surrogate form (PATIENT_1)~~: resolved 2026-10-24 (ADR-0015): doctors
  see the originals, the approved record holds them, models, logs and traces stay surrogate-only.

- Langfuse free tier: resolved for the future on 2026-10-13 (collector filter + `no-log` for bulk calls); the
  current month stays suspended until a new organisation key or the reset.

- Hybrid (step 2) did not beat dense at the top ranks with plain RRF. Do not tune RRF weights or k on the
  golden set (that would fit the test set); if a weighted fusion is tried, use 2-fold cross-validation over
  the questions. The golden questions were written to avoid copying 6+ words from the source, which may
  slightly disadvantage BM25 against real spoken questions; ASR transcripts in Phase 4 are a second check.

- Gold chunks are quote-based, so a chunk that answers in other words counts as a miss (2 of 6 sampled
  misses). Options: pooled relevance judgements (judge the union of each system's top 10 once, store as
  `also_relevant`), or keep quote-based gold and report it as a lower bound. **Decided 2026-10-13 (you):
  lower bound**, stated in `evals/reports/rag/ablation.md`.

- Corpus quality (task 1 follow-up): WHO 344424 outline entries are figures ("Fig. 2 Framework for
  analysis"), so its section titles are misleading, and reference-list pages are indexed as chunks.
  Fixing changes chunk ids and costs a 66-min re-embed on CPU; golden gold ids are recomputed from quotes
  (`just golden --expand`), so the fix can wait for the next planned re-embed (tasks 7–8).

- Embedding speed: CPU gives 2.0 chunks/s (66 min for the corpus). Resolved: the re-embeds for tasks 7
  and 8 ran on CPU (81 and ~70 min); GPU torch was not needed.

- Latency: Groq `gpt-oss-20b` answered ~3× faster than the Gemini pool (p95 1.1 s vs 3.8 s), mostly Gemini's
  reasoning time. The Phase 4 voice budget (TTFA p95 < 1.5 s) will need a faster model or a lower thinking
  level for Ask mode; choose from the Phase 2/4 evals.
- Decided 2026-10-06 (you): the primary alias spreads over four Gemini Flash models (`gemini-3.5-flash`,
  `gemini-3.6-flash`, `gemini-3.5-flash-lite`, `gemini-2.5-flash`), each with its own 20 requests/day free
  quota. Their answer quality differs; the Phase 2 eval decides which stay.

- **De-ID generalisation (after v1).** On the frozen held-out set, names 0.973 and places 0.850: misses are
  places without a cue ("originally from X", "works in X") and a second name in a list. Seeded scores are
  optimistic (cues were designed on that set). Next steps: Phase 2 transcripts as a harder test, a new
  held-out set for any further tuning, and the Phase 5 fine-tuned NER. Known gap: an uncommon first name that
  is also a drug brand (e.g. "Allegra") is not redacted when it appears alone with no cue (ADR-0004).
  **Update 2026-10-24:** the fine-tuned tagger (ADR-0014) finds every name and place on held-out v3
  (frozen before round 2 was trained; v2 also, but round 2's data was written after seeing it);
  spaCy rules stay the default. Real dictation is still the harder, untested case.
- `/reidentify` HTTP route: built 2026-10-24 (ADR-0015), callable only by the API, audited.

- Gemini 3.x Flash and Groq gpt-oss reason before answering; reasoning tokens count against `max_tokens`
  (16 tokens returned empty text) and add latency. Decide the thinking level per task from the Phase 2/4
  latency and quality evals, then set it in `config/models.yaml`.
- LiteLLM's response `model` field echoes the alias for the primary but names the real deployment after
  failover. The spend log (`model`, `model_group`) is the reliable record; task 7 traces should use it.
- HAPI uses 1.52 of its 2 GB limit with 50 patients. Watch it when adding data; raise the limit or the heap only
  with a measurement.

- Core + fhir + rag + voice was estimated at ~10.2 GB, above the 10 GB WSL cap. Resolved in Phase 4: the
  voice agent and the Scribe listener run on the host (LiveKit console mode), so the `voice` profile is
  not started; core + fhir + rag measured 5.9 GiB with the de-ID tagger (2026-10-24).
- The package name `agents/` clashes with the OpenAI Agents SDK import name (`agents`). The Phase 3
  framework comparison should run in its own isolated project under `evals/agents/`.
- SPEC §3 and §6 still contain embedded-diagram placeholders (architecture, RAG pipeline). Text is enough
  for now; re-export if the diagrams are wanted in the repo.
