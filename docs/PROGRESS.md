# ClinScribe — Progress

Last updated: 2026-10-06 · Current phase: **1 — Foundations: exit gate PASSES (`just gate 1` from a fresh clone);
left: two task 11 checks that need you (red PR, branch protection)**

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
| 2 | **ADRs:** 0001 gateway scope, 0002 Langfuse Cloud vs self-hosted, 0003 Compose profiles and memory budget. | `tests/unit/test_adr_format.py`: every ADR has Context, Options, Decision, Consequences headings. You review and approve the text. | ✅ test passes; text awaiting your review |
| 3 | **Core Compose stack:** postgres (init script creates `clinscribe`, `litellm`, `hapi` databases and least-privilege roles), otel-collector, litellm, deid, api (one Python image), hapi-fhir (profile `fhir`); memory limits and healthchecks on every service. | `just up` → `tests/integration/test_stack_health.py`: all services healthy within 5 min. `just stats` total recorded below; target ≤ 8 GB. | ✅ 2026-10-05: 9/9 stack tests pass; 1.94 GB measured |
| 4 | **HAPI FHIR + Synthea:** pinned Synthea release (SHA-256 checked), seed 42, 50 patients, loaded in dependency order by `just fhir-load`; idempotent. | Integration tests: Patient count == 50; every patient has ≥ 1 Encounter; search by family name works; a second `just fhir-load` leaves the count at 50. | ✅ 2026-10-05: 4/4 pass (gate c) |
| 5 | **LiteLLM gateway with failover:** alias with the 4-step fallback chain, per-key budget and rpm, spend logs without prompt text, `config/models.yaml` (task → alias), `llmops/gateway/client.py` (accepts only `DeidentifiedText`), record/replay cache for tests, chaos switch `just chaos primary-down`. | Unit: client rejects a plain `str`; a replay-cache hit makes zero network calls. Live (`just test-live`): with the primary down, a request succeeds, the response names the Groq model, and the failover appears in spend logs. Ollama step is skipped if Ollama is not running. | ✅ 2026-10-05: live 2 pass, Ollama step skipped (model downloading) (gate a) |
| 6 | **De-ID service v0:** Presidio + spaCy `en_core_web_lg` + custom recognisers for the 18 Safe Harbor types; consistent surrogates per encounter (`PATIENT_1`); Fernet-encrypted mapping in Postgres; FastAPI `/deidentify` (and internal-only `/reidentify`). Seeded fake-PHI corpus generated with Faker. | `just eval privacy` writes `evals/reports/privacy/deid_v0.md` with recall per entity type. Structured types (MRN, phone, email, SSN, dates, ZIP, URL, IP, IDs) recall = 1.0; name recall recorded as the Phase 5 baseline. Same input → same surrogates. Raw DB row contains no plaintext. | ✅ 2026-10-05: 15/15 structured types recall 1.000; PERSON 0.95, LOCATION 0.75 (baseline) |
| 7 | **Telemetry with redaction:** OTel setup in `llmops/telemetry` with GenAI semantic-convention attributes; redacting exporter wrapper + logging redaction filter; collector redaction processor → Langfuse Cloud (EU) + local file exporter; LiteLLM OTel callback → collector. | Unit: a span and a log record carrying seeded PHI are exported without it. Integration: one request → one Langfuse trace (fetched via API) with api → deid → gateway spans and `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`. | ✅ 2026-10-05: unit 4/4, integration 2/2 (local export + Langfuse, no PHI); the api → deid → gateway chain check moves to task 9 (needs the endpoint) |
| 8 | **Audit table:** append-only, hash-chained (HMAC-SHA-256 with `AUDIT_CHAIN_KEY`); DB trigger blocks UPDATE/DELETE; app role has INSERT/SELECT only; advisory lock keeps order; `just audit-verify`. | Tests: chain verifies after 100 appends including 10 concurrent; UPDATE and DELETE as the app role raise; a manual tamper (as owner) is reported at the exact row. | ✅ 2026-10-05: 8/8 pass; `just audit-verify` OK |
| 9 | **Pipeline endpoint:** FastAPI `/health` and `POST /v1/dev/complete` (text → deid → gateway → answer), writing an audit record (actor, model, prompt version, trace id). | Integration: the endpoint returns an answer; an audit row exists with the same trace id as the Langfuse trace. | ✅ 2026-10-05: live 1/1 (answer, audit row = trace id, Langfuse trace has api + deid + gateway spans, no seeded PHI) |
| 10 | **PHI leak test (gate b):** `evals/privacy/leak_test.py` seeds 20 transcripts with fake PHI, sends them through the endpoint, then scans the collector file export, `docker compose logs` for every service, Langfuse traces for the run, LiteLLM spend logs and the audit table. | 0 leaks. Positive control: the scanner finds 100% of seed values in a planted file. Report in `evals/reports/privacy/`. | ✅ 2026-10-05: 0 leaks in 6 sinks (66 seed values), control 100% (gate b) |
| 11 | **CI** (after you add the GitHub remote): `.github/workflows/ci.yml` runs ruff, mypy and unit tests on every PR (replay cache, no secrets); integration job (core + fhir) on push to `main` and manual dispatch. | A PR shows green; a throwaway PR with a failing test goes red. You enable branch protection on `main` requiring CI. | ◐ 2026-10-06: run #3 on `33e7fd3` green (lint-unit 21 s, integration 8 m 2 s); red-PR check and branch protection pending (you) |
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

## Next

- You: finish task 11 — open a throwaway PR with a deliberately failing test and confirm CI goes red (I can
  prepare the branch), then add branch protection on `main` requiring the `lint-unit` check.
- Then Phase 1 is closed. Before Phase 2: decide the de-ID name/place gap (Open questions), and plan Phase 2.
- You (recommended after the 0x1A blue screen): run Windows Memory Diagnostic (`mdsched.exe`).
- `just gate 1` from the fresh clone, `just eval latency`; record p50/p95 here; close task 12.
- Push the CI fix, add the repository secrets, confirm both CI jobs are green; close task 11.

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

- Latency: Groq `gpt-oss-20b` answered ~3× faster than the Gemini pool (p95 1.1 s vs 3.8 s), mostly Gemini's
  reasoning time. The Phase 4 voice budget (TTFA p95 < 1.5 s) will need a faster model or a lower thinking
  level for Ask mode; choose from the Phase 2/4 evals.
- Decided 2026-10-06 (you): the primary alias spreads over four Gemini Flash models (`gemini-3.5-flash`,
  `gemini-3.6-flash`, `gemini-3.5-flash-lite`, `gemini-2.5-flash`), each with its own 20 requests/day free
  quota. Their answer quality differs; the Phase 2 eval decides which stay.

- **PHI reaching the LLM (outside gate b).** Gate b passes because traces, logs and stores never hold
  message text. But the LLM still saw 2 of 66 seed values in the leak run (both invented place names that
  spaCy missed); the de-ID eval shows PERSON 0.95 and LOCATION 0.75 recall. CLAUDE.md requires no PHI to reach
  an LLM. Options: a place/name gazetteer recogniser (cheap, measurable), `en_core_web_lg` (compare in the
  eval), or pull the Phase 5 LoRA NER forward. Recommend deciding before Phase 2 sends real-looking
  transcripts; it does not block the Phase 1 gates as written.
- De-ID model changed from the planned `en_core_web_lg` to `en_core_web_md` (33 MB vs 401 MB on a slow link,
  ~0.3 vs ~1 GB RAM, near-equal published NER F1); `DEID_SPACY_MODEL` switches it for a comparison.
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
