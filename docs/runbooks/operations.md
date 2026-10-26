# Operations runbook

Start-up and first install: `docs/runbooks/local-setup.md`. Every command runs from the repo root in
PowerShell; nothing below prints a secret.

## Start, check, stop

| Task | Command |
|---|---|
| Core + FHIR (Phase 1–3 API, de-ID, gateway, fhir-mcp) | `just up` |
| Add retrieval, drug graph and their MCP servers | `just up rag` |
| Browser voice (WebRTC, ADR-0019) | `just up voice`, then `just voice dev` (agent worker, own terminal), then the Voice tab; check with `just voice-webrtc [dr-second]` (the report lists the audit rows, which must name that doctor). The worker reads `VOICE_AGENT_KEY` from `.env`; if it is missing or wrong, the agent says it cannot confirm who is asking and answers nothing |
| Review UI (dev server, http://localhost:5173) | `npm --prefix apps/web run dev` |
| Health, memory | `just ps`, `just stats` (budget ≤ 8 GB) |
| Local trace UI (Arize Phoenix, ADR-0024) | `just phoenix on` (127.0.0.1:6006, no login: local use only; ~60 s to start the first time), `just phoenix off` to stop it and restore the collector. Use it when Langfuse Cloud refuses ingestion or traces must stay on the machine |
| Dashboards (ADR-0023) | `just up obs`, then `just migrate` once (Grafana's read-only spend-log login); Grafana on http://127.0.0.1:3000, user `admin`, password `GRAFANA_ADMIN_PASSWORD` in `.env`; dashboard "ClinScribe operations". Prometheus on :9090 keeps 15 days |
| Stop (data volumes kept) | `just down` |
| Phase gates | `just gate 1` … `just gate 5` |
| Retention limits (ADR-0022) | `just retention` (dry run), then `just retention --apply`; schedule it daily, e.g. Windows Task Scheduler running `just retention --apply` in the repo |
| GDPR erasure request | `just erase <patient id> --request <ticket id> --by <admin user>` (dry run: shows the counts), then the same with `--apply`; the audit row `gdpr.erasure` is the record. Requests about the clinical record itself go to the EHR's controller |

## Rotate a key

1. Generated keys (`LITELLM_*`, DB passwords, `DEID_MAPPING_KEY`, `AUDIT_CHAIN_KEY`,
   `APPROVAL_TOKEN_KEY`, `AUTH_TOKEN_KEY`, `VOICE_AGENT_KEY`, `QDRANT_API_KEY`, `NEO4J_PASSWORD`):
   clear the value in `.env`, run `just gen-keys`, then `just up rag` (containers pick up the new
   value). `RETENTION_DB_PASSWORD`: `just gen-keys`, then `just migrate` (resets the login).
2. Special cases:
   - `AUTH_TOKEN_KEY` / `APPROVAL_TOKEN_KEY`: all issued tokens and pending approvals become invalid
     (intended). Users sign in again; pending drafts must be re-approved.
   - `AUDIT_CHAIN_KEY`: the existing chain no longer verifies with the new key. Run
     `just audit-verify` first, export the head hash, then rotate and record the rotation in the log
     (a real deployment keeps old keys for verification).
   - `DEID_MAPPING_KEY`: existing surrogate mappings cannot be decrypted; rotate only with a
     re-encryption job (not built).
   - `DEID_REIDENTIFY_KEY`: only the API and the de-ID service hold it; rotate like the plain keys
     and restart both (`just up`), nothing else is affected (ADR-0015).
   - `VOICE_AGENT_KEY`: only the API and the voice worker hold it; rotate, `just up voice`, then
     restart the worker (`just voice dev`); tokens already delegated expire within 30 minutes
     (ADR-0019). Rotate at once if it may have leaked: it lets its holder ask as any doctor.
   - LiteLLM virtual keys: `just gateway-keys` re-registers them with their limits.
3. Provider keys (Gemini, Groq, OpenRouter, Langfuse): paste the new value into `.env`, `just up`.

## Re-index the corpus

After corpus changes (`just ingest`): `just index` (dense, ~66 min CPU), `just contextual` (prefixes,
local model, hours), `just index --variant contextual`, `just index-colbert --variant contextual`,
`just graph`; then `just eval rag` and compare with `evals/reports/rag/ablation.md` before switching.
The CI fixture (`tests/fixtures/rag_mini`) is rebuilt only for intended changes
(`uv run python -m evals.rag.fixture`).

## Roll back a prompt

Prompts are versioned files (`prompts/*.yaml`, `id@vN` in every trace and audit row).
1. `git log -p prompts/<name>.yaml` to find the last good version.
2. Restore it with a new version number (never reuse a number), commit, `just up` (the API reloads).
3. Confirm in the audit log (`GET /v1/audit`) that new rows carry the restored version, and re-run the
   affected evaluation (`just eval redteam`, `uv run python -m evals.agents.note_eval`).

## Incident response

1. Find the window in the audit log (`GET /v1/audit`, admin/operator) and the trace ids it carries.
2. Read the spans: `.artifacts/otel/traces.jsonl` locally (Langfuse when ingesting).
3. Gateway: `just logs litellm`; spend log names the deployment that served each call.
4. Drills and their postmortems: `docs/postmortems/` (`just chaos primary-down|cloud-down on|off`).
