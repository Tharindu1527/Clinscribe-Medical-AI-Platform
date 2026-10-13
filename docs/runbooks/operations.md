# Operations runbook

Start-up and first install: `docs/runbooks/local-setup.md`. Every command runs from the repo root in
PowerShell; nothing below prints a secret.

## Start, check, stop

| Task | Command |
|---|---|
| Core + FHIR (Phase 1–3 API, de-ID, gateway, fhir-mcp) | `just up` |
| Add retrieval, drug graph and their MCP servers | `just up rag` |
| Review UI (dev server, http://localhost:5173) | `npm --prefix apps/web run dev` |
| Health, memory | `just ps`, `just stats` (budget ≤ 8 GB) |
| Stop (data volumes kept) | `just down` |
| Phase gates | `just gate 1` … `just gate 5` |

## Rotate a key

1. Generated keys (`LITELLM_*`, DB passwords, `DEID_MAPPING_KEY`, `AUDIT_CHAIN_KEY`,
   `APPROVAL_TOKEN_KEY`, `AUTH_TOKEN_KEY`, `QDRANT_API_KEY`, `NEO4J_PASSWORD`): clear the value in `.env`,
   run `just gen-keys`, then `just up rag` (containers pick up the new value).
2. Special cases:
   - `AUTH_TOKEN_KEY` / `APPROVAL_TOKEN_KEY`: all issued tokens and pending approvals become invalid
     (intended). Users sign in again; pending drafts must be re-approved.
   - `AUDIT_CHAIN_KEY`: the existing chain no longer verifies with the new key. Run
     `just audit-verify` first, export the head hash, then rotate and record the rotation in the log
     (a real deployment keeps old keys for verification).
   - `DEID_MAPPING_KEY`: existing surrogate mappings cannot be decrypted; rotate only with a
     re-encryption job (not built).
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
