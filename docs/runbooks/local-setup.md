# Runbook: local set-up and the Phase 1 gate

From a fresh clone to a passing `just gate 1` on Windows (PowerShell). Linux and macOS work the same
way with `sh`. All data is synthetic.

## 1. Prerequisites (once per machine)

| Tool | Notes |
|---|---|
| Docker Desktop (WSL2) | Cap WSL memory in `%USERPROFILE%\.wslconfig`: `memory=10GB`, `swap=4GB`, and `swapFile` on a drive with space; `wsl --shutdown` after editing. |
| uv | Installs Python 3.11 and every dependency: `uv python install 3.11`. |
| just | `uv tool install rust-just` (no admin rights needed). |
| Ollama (optional until Phase 5) | Install to a roomy drive (`OllamaSetup.exe /DIR="D:\Ollama"`), set `OLLAMA_MODELS`, then `ollama pull llama3.2:3b`. |

Low disk space on C:? Point the caches elsewhere (`UV_CACHE_DIR`, `UV_PYTHON_INSTALL_DIR`, `UV_TOOL_DIR`,
`OLLAMA_MODELS`, `HF_HOME`, npm cache) and keep the Windows page file off C:. `just doctor` warns about each.

## 2. Secrets

```
just gen-keys
```

This creates `.env` from `.env.example` and fills the generated secrets (database passwords, gateway keys,
de-ID and audit keys) without printing them. Then paste the five free-tier keys into `.env`:
`GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`
(Langfuse: an EU project at cloud.langfuse.com). `.env` is git-ignored.

Do not regenerate secrets after the first `just up`: Postgres stores the database passwords on first start.

## 3. Start, load, check

```
just doctor          # prerequisites, memory cap, caches off C:
uv sync              # Python 3.11 environment
just lint            # ruff + mypy
just test-unit       # fast, no Docker
just up              # core + fhir profiles; waits until healthy (~2.5-3 GB RAM)
just migrate         # de-ID mapping and audit tables (idempotent)
just gateway-keys    # app key with budget and rate limit (idempotent)
just fhir-load       # Synthea v4.0.0, seed 42, 50 patients (idempotent)
just gate 1          # Phase 1 exit gate, prints PASS/FAIL per check
```

`just gate 1` makes about 25 real free-tier LLM calls and takes about 15 minutes. It runs the full
test suite with the stack required, the FHIR checks, the live failover and pipeline tests, the PHI leak
test and the audit chain check.

## 4. Everyday commands

| Command | What it does |
|---|---|
| `just ps` / `just logs <service>` | Status and logs |
| `just stats` | Memory per container against the 8 GB budget |
| `just down` | Stop everything (data volume kept) |
| `just chaos primary-down on\|off` | Cut the primary LLM provider off and back on |
| `just eval privacy` / `just eval leak` / `just eval latency` | De-ID recall, leak test, failover latency |
| `just audit-verify` | Recompute the audit hash chain |

## 5. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Database calls take ~30 s | `localhost` resolves to IPv6 `::1` first on Windows; use `127.0.0.1` in `.env` (the default). |
| `docker compose` "unknown command" | Docker CLI plugins point at a missing folder; add `cliPluginsExtraDirs` with Docker's `resources\cli-plugins` to `~/.docker/config.json`. |
| `just` cannot find `powershell.exe` | The justfile uses its full path; check `C:\Windows\System32\WindowsPowerShell\v1.0` exists. |
| C: fills during long runs | The system-managed page file grows on C:; move it to another drive and reboot; `just down` when idle. |
| Langfuse read returns HTTP 410 | Legacy traces API is gone for new organisations; use `/api/public/v2/observations`. |
