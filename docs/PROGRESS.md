# ClinScribe — Progress

Last updated: 2026-10-06 · **Phase 1 — Foundations: COMPLETE (2026-10-06)**; de-ID v1 merged (PR #1).
**Phase 2 — Advanced RAG: in progress (tasks 0–2, 4–6 done; 3 awaiting review)**. Phases in total: 6 (SPEC §12).

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
| rag (Phase 2) | qdrant, neo4j (heap 768 MB + page cache 512 MB), local encoders in api | ~3.5 GB |
| voice (Phase 4) | livekit-server, voice-agent, web | ~1.7 GB |
| obs (optional) | prometheus, grafana | ~0.4 GB |
| tools (one-shot) | synthea generator | ~1.0 GB while running |
| Ollama (Windows host, outside WSL cap) | ~3B Q4 model | ~2.5 GB VRAM + ~1 GB RAM |

## Phase 2 — Advanced RAG (weeks 3–5)

**Phase exit gate (SPEC §12):** the ablation report shows the chosen pipeline beats dense-only on
**recall@10** and **faithfulness** (paired bootstrap 95% CI for each difference). Run with `just gate 2`.

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
| 7 | Contextual retrieval with local-LLM prefixes (step 4) | Prefixes cached; step 4 vs best so far | ☐ |
| 8 | Late chunking (step 5), compared with contextual, not stacked | Step 5 vs best so far | ☐ |
| 9 | Neo4j drug graph (DDInter + RxNorm) and GraphRAG for drug questions (step 6) | Graph counts; interaction-question subset vs best | ☐ |
| 10 | Generation with chunk-id citations, citation check, faithfulness (RAGAS via the gateway) | Faithfulness and citation precision: baseline vs best two | ☐ |
| 11 | Vector-store ADR: Qdrant vs pgvector on recall and latency | ADR with numbers | ☐ |
| 12 | CI regression (retrieval metrics on a committed mini fixture index, no secrets) + `just gate 2` | `just gate 2` passes; CI goes red when recall drops | ☐ |

Memory measured 2026-10-06 (core + fhir + rag, index loaded): **3.59 GB** of containers (Neo4j 1,127 MB, Qdrant 251 MB);
the encoder runs on the host (~1.7 GB while embedding), outside the WSL cap.

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

## Next
- **You (or a clinician reviewer): fill `evals/golden/review/review_v1.csv`** (49 rows; open in Excel;
  verdict ok / fix / reject, notes, reviewer, date), then I apply fixes and close task 3.
- You: review ADR-0006 (reranker: ColBERT over the hybrid pool).
- Phase 2 task 7: contextual retrieval (step 4). Design point: Anthropic-style prefixes put the whole document
  in the prompt, but the local model runs with a 2,048-token context and WHO PDFs are 100+ pages, so the
  context given to the LLM will be the section (title + section heading + nearby text); 8,104 prefixes on the
  local 3B model through the gateway (no quota), cached; then re-embed dense (66 min) and ColBERT (14 min).
- You (recommended after the 0x1A blue screen): run Windows Memory Diagnostic (`mdsched.exe`).

## Blockers

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

- Hybrid (step 2) did not beat dense at the top ranks with plain RRF. Do not tune RRF weights or k on the
  golden set (that would fit the test set); if a weighted fusion is tried, use 2-fold cross-validation over
  the questions. The golden questions were written to avoid copying 6+ words from the source, which may
  slightly disadvantage BM25 against real spoken questions; ASR transcripts in Phase 4 are a second check.

- Gold chunks are quote-based, so a chunk that answers in other words counts as a miss (2 of 6 sampled
  misses). Options: pooled relevance judgements (judge the union of each system's top 10 once, store as
  `also_relevant`), or keep quote-based gold and report it as a lower bound. Decide before the ablation
  report (task 12); a judged pool also helps the faithfulness evaluation.

- Corpus quality (task 1 follow-up): WHO 344424 outline entries are figures ("Fig. 2 Framework for
  analysis"), so its section titles are misleading, and reference-list pages are indexed as chunks.
  Fixing changes chunk ids and costs a 66-min re-embed on CPU; golden gold ids are recomputed from quotes
  (`just golden --expand`), so the fix can wait for the next planned re-embed (tasks 7–8).

- Embedding speed: CPU gives 2.0 chunks/s (66 min for the corpus). Contextual retrieval (task 7) and late
  chunking (task 8) re-embed the corpus. Options: the int8 ONNX export in the same model repo (CPU), or CUDA
  torch on the RTX 3050 (~2.5 GB download). Decide before task 7 with a 500-chunk timing of each.

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
- `/reidentify` HTTP route deferred to Phase 3 (needs authentication); re-identification exists as a library
  function with a round-trip test.

- Gemini 3.x Flash and Groq gpt-oss reason before answering; reasoning tokens count against `max_tokens`
  (16 tokens returned empty text) and add latency. Decide the thinking level per task from the Phase 2/4
  latency and quality evals, then set it in `config/models.yaml`.
- LiteLLM's response `model` field echoes the alias for the primary but names the real deployment after
  failover. The spend log (`model`, `model_group`) is the reliable record; task 7 traces should use it.
- HAPI uses 1.52 of its 2 GB limit with 50 patients. Watch it when adding data; raise the limit or the heap only
  with a measurement.

- Core + fhir + rag + voice is ~10.2 GB, above the 10 GB WSL cap, so the Phase 4 demo won't fit as is.
  Options: raise the cap to 12 GB, trim the HAPI heap to 1 GB, or stop `rag` services that voice does not need.
  Decide in Phase 4.
- The package name `agents/` clashes with the OpenAI Agents SDK import name (`agents`). The Phase 3
  framework comparison should run in its own isolated project under `evals/agents/`.
- SPEC §3 and §6 still contain embedded-diagram placeholders (architecture, RAG pipeline). Text is enough
  for now; re-export if the diagrams are wanted in the repo.
