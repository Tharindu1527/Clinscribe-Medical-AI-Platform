# ClinScribe — Progress

Last updated: 2026-10-04 · Current phase: **1 — Foundations (not started; plan awaiting approval)**

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
| 0 | **Prerequisites (you):** install Docker Desktop (WSL2, `.wslconfig` memory=10GB), `just`, Ollama + one ~3B quantized model; `uv self update`; `uv python install 3.11`. | `docker info`, `just --version`, `ollama list` (model present) and `uv python find 3.11` all succeed. | ☐ |
| 1 | **Repo skeleton and tooling:** `pyproject.toml` (Python 3.11, ruff, mypy, pytest markers `unit`/`integration`/`live`), package folders, `justfile` (PowerShell shell), `.env.example`, `.gitignore`, `data/LICENSES.md`, `config/settings.py` (pydantic-settings, `SecretStr`), ruff banned-import rule for provider SDKs outside `llmops/gateway`. | On a clean clone, `uv sync; just lint; just test` pass. Tests: every Settings field has a key in `.env.example` and vice versa; `repr(Settings())` contains no secret value; a fixture that imports `openai` outside the gateway makes `ruff check` fail. | ☐ |
| 2 | **ADRs:** 0001 gateway scope, 0002 Langfuse Cloud vs self-hosted, 0003 Compose profiles and memory budget. | `tests/unit/test_adr_format.py`: every ADR has Context, Options, Decision, Consequences headings. You review and approve the text. | ☐ |
| 3 | **Core Compose stack:** postgres (init script creates `clinscribe`, `litellm`, `hapi` databases and least-privilege roles), otel-collector, litellm, deid, api (one Python image), hapi-fhir (profile `fhir`); memory limits and healthchecks on every service. | `just up` → `tests/integration/test_stack_health.py`: all services healthy within 5 min. `just stats` total recorded below; target ≤ 8 GB. | ☐ |
| 4 | **HAPI FHIR + Synthea:** pinned Synthea release (SHA-256 checked), seed 42, 50 patients, loaded in dependency order by `just fhir-load`; idempotent. | Integration tests: Patient count == 50; every patient has ≥ 1 Encounter; search by family name works; a second `just fhir-load` leaves the count at 50. | ☐ |
| 5 | **LiteLLM gateway with failover:** alias with the 4-step fallback chain, per-key budget and rpm, spend logs without prompt text, `config/models.yaml` (task → alias), `llmops/gateway/client.py` (accepts only `DeidentifiedText`), record/replay cache for tests, chaos switch `just chaos primary-down`. | Unit: client rejects a plain `str`; a replay-cache hit makes zero network calls. Live (`just test-live`): with the primary down, a request succeeds, the response names the Groq model, and the failover appears in spend logs. Ollama step is skipped if Ollama is not running. | ☐ |
| 6 | **De-ID service v0:** Presidio + spaCy `en_core_web_lg` + custom recognisers for the 18 Safe Harbor types; consistent surrogates per encounter (`PATIENT_1`); Fernet-encrypted mapping in Postgres; FastAPI `/deidentify` (and internal-only `/reidentify`). Seeded fake-PHI corpus generated with Faker. | `just eval privacy` writes `evals/reports/privacy/deid_v0.md` with recall per entity type. Structured types (MRN, phone, email, SSN, dates, ZIP, URL, IP, IDs) recall = 1.0; name recall recorded as the Phase 5 baseline. Same input → same surrogates. Raw DB row contains no plaintext. | ☐ |
| 7 | **Telemetry with redaction:** OTel setup in `llmops/telemetry` with GenAI semantic-convention attributes; redacting exporter wrapper + logging redaction filter; collector redaction processor → Langfuse Cloud (EU) + local file exporter; LiteLLM OTel callback → collector. | Unit: a span and a log record carrying seeded PHI are exported without it. Integration: one request → one Langfuse trace (fetched via API) with api → deid → gateway spans and `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`. | ☐ |
| 8 | **Audit table:** append-only, hash-chained (HMAC-SHA-256 with `AUDIT_CHAIN_KEY`); DB trigger blocks UPDATE/DELETE; app role has INSERT/SELECT only; advisory lock keeps order; `just audit-verify`. | Tests: chain verifies after 100 appends including 10 concurrent; UPDATE and DELETE as the app role raise; a manual tamper (as owner) is reported at the exact row. | ☐ |
| 9 | **Pipeline endpoint:** FastAPI `/health` and `POST /v1/dev/complete` (text → deid → gateway → answer), writing an audit record (actor, model, prompt version, trace id). | Integration: the endpoint returns an answer; an audit row exists with the same trace id as the Langfuse trace. | ☐ |
| 10 | **PHI leak test (gate b):** `evals/privacy/leak_test.py` seeds 20 transcripts with fake PHI, sends them through the endpoint, then scans the collector file export, `docker compose logs` for every service, Langfuse traces for the run, LiteLLM spend logs and the audit table. | 0 leaks. Positive control: the scanner finds 100% of seed values in a planted file. Report in `evals/reports/privacy/`. | ☐ |
| 11 | **CI** (after you add the GitHub remote): `.github/workflows/ci.yml` runs ruff, mypy and unit tests on every PR (replay cache, no secrets); integration job (core + fhir) on push to `main` and manual dispatch. | A PR shows green; a throwaway PR with a failing test goes red. You enable branch protection on `main` requiring CI. | ☐ |
| 12 | **Phase 1 exit:** `just gate 1`; `docs/runbooks/local-setup.md`; failover latency p50/p95 (20 calls, normal vs primary down); measured memory per service. | On a fresh clone, following the runbook: `just up; just fhir-load; just gate 1` passes. PROGRESS updated with the numbers. | ☐ |

### Memory budget (estimates, to be replaced by `just stats` measurements in task 3)

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

- 2026-10-04: SPEC §12 roadmap written in; SPEC wording updated for free tiers, Gemini Live,
  Ollama-only local fallback and Langfuse Cloud; gateway-scope rule added to CLAUDE.md;
  branch renamed `master` → `main`; this file created.

## Next

- Get approval for the Phase 1 plan (structure, Compose services, justfile, `.env.example` keys).
- Task 0 (you), then task 1.

## Blockers

- `just`, Docker Desktop and Ollama are not installed on the dev machine (checked 2026-10-04).
  uv 0.6.4 is present; Python 3.11 not yet installed (system Python is 3.10).
- GitHub remote not yet created (needed for task 11).

## Open questions

- Core + fhir + rag + voice is ~10.2 GB, above the 10 GB WSL cap, so the Phase 4 demo won't fit as is.
  Options: raise the cap to 12 GB, trim the HAPI heap to 1 GB, or stop `rag` services that voice does not need.
  Decide in Phase 4.
- The package name `agents/` clashes with the OpenAI Agents SDK import name (`agents`). The Phase 3
  framework comparison should run in its own isolated project under `evals/agents/`.
- SPEC §3 and §6 still contain embedded-diagram placeholders (architecture, RAG pipeline). Text is enough
  for now; re-export if the diagrams are wanted in the repo.
- CLAUDE.md still mentions vLLM (Stack and Platform sections), which is now out of scope. Update?
- SPEC §10 repository tree will be synced once the final structure is approved.
- Langfuse Cloud region: EU (`cloud.langfuse.com`) assumed, which fits the GDPR story.
