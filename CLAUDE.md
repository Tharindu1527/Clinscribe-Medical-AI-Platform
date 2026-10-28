# ClinScribe — Voice Clinical Copilot

Portfolio project: a voice-first clinical copilot (Scribe, Ask, Lab modes) that applies
real-time voice AI, agents, advanced RAG, LLMOps and healthcare compliance end to end.

Full specification: @docs/SPEC.md
Current status and next steps: @docs/PROGRESS.md

## Non-negotiable rules
- Synthetic or public data only. Never use, generate or request real patient data.
- No PHI may reach an LLM, a log or a trace before passing `privacy/deid`.
- All LLM calls go through the LiteLLM gateway (`llmops/gateway`). Never call a provider SDK
  directly from app code. The only exception is the voice speech-to-speech plugin, documented in an ADR.
- Gateway scope (ADR-0001): text generation and hosted embeddings go through the gateway; local encoders
  (embeddings, rerankers, NER) run in-process on de-identified text only; RAGAS/DeepEval use the gateway URL.
- Clinical writes (FHIR create/update) happen only after a human-in-the-loop approval token.
- Secrets live only in `.env` (git-ignored). Never print, log, commit or hard-code keys.
- Every clinical claim in an answer must carry a citation to a source chunk id.

## Stack
Python 3.11 (managed with uv), FastAPI, Pydantic v2, LangGraph, MCP Python SDK,
LiveKit Agents, Qdrant + BM25, Neo4j, HAPI FHIR (Synthea data), LiteLLM, Langfuse,
OpenTelemetry, Presidio, RAGAS, DeepEval, pytest, React (Vite), Docker Compose, k6.

Free-tier providers behind the gateway: Gemini Flash, Groq, OpenRouter `:free` models,
local Ollama (host GPU, last fallback). Speech: Deepgram, AssemblyAI. TTS: Cartesia / ElevenLabs free tiers.

## Platform
- Development machine: native Windows, PowerShell + Git Bash, Docker Desktop (WSL2 backend).
- Use `just` (justfile) for task commands, not make. Scripts must work in PowerShell.
- All infrastructure services run in Docker. Use forward slashes in paths inside code and configs.
- Local models: Ollama for Windows (RTX 3050, 4 GB VRAM). No vLLM. LoRA fine-tuning runs on Colab/Kaggle.
- Disk: C: is almost full. Every install, cache, model, dataset and temp output goes on D:
  (`D:\devcache\...`, Docker data in `D:\Docker\wsl`, run output in `.artifacts/`). `just doctor` checks it.
- Memory: WSL2 is capped at 10 GB; `just up` (core stack) must stay under ~8 GB. Use Compose profiles.

## Commands (created in Phase 1; keep this list current)
- `just doctor` — check prerequisites; `just gen-keys` — fill generated secrets in `.env`
- `just up` / `just down` — start (core + fhir; `just up rag` adds a profile) or stop the stack;
  `just up voice` + `just voice dev` for browser voice (ADR-0019), `just voice-webrtc` to check it;
  `just up obs` for the Grafana dashboards (ADR-0023); `just phoenix on|off` local traces (ADR-0024);
  `just ps`, `just logs <svc>`, `just stats` (memory vs the 8 GB budget)
- `just test` — unit and integration tests; `just test-unit`; `just test-live` (real provider calls)
- `just lint` — ruff + mypy; `just fmt` to auto-fix
- `just eval` — evaluation suite; writes reports to `evals/reports/`
- `just retention` / `just erase <patient> --request <ticket> --by <admin>` — retention limits
  and GDPR erasure (dry run; add `--apply`; ADR-0022); `just access-report` the Art. 15 copy
- `just edit-pairs` — doctors' edits exported as evaluation data after a PHI scan (ADR-0028)
- `just load` — load tests; reports p50/p95

## How to work in this repo
- Work one phase at a time, following SPEC section 12. Do not start the next phase until the
  current phase's exit gate passes.
- For any change touching more than 3 files, plan first and wait for approval.
- Before saying a task is done: run `just lint` and `just test` and show the result.
  For latency work, show p50 and p95, not averages.
- Prefer the simplest design that can be measured. Add a dependency only with a one-line reason.
- Record significant decisions as ADRs in `docs/adr/NNNN-short-title.md`
  (context, options, decision, consequences).
- Small commits with conventional messages (feat:, fix:, test:, docs:, chore:).
- At the end of every session, update `docs/PROGRESS.md`: done, next, blockers, open questions.
- Free-tier APIs are rate limited: cache LLM responses in tests, use small eval subsets during
  development, and run the full eval only when asked.

## Layout
apps/web, apps/api, voice/, agents/, mcp_servers/, retrieval/, privacy/deid/, llmops/,
prompts/, config/, finetune/, evals/, load_tests/, tests/ (unit, integration), scripts/, infra/,
data/ (git-ignored except LICENSES.md), docs/ (adr, postmortems, compliance, runbooks)
