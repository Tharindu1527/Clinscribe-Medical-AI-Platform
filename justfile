# ClinScribe task runner. Recipes run in PowerShell on Windows and sh elsewhere.
# Full path: some Windows setups (including the dev machine) lack the PowerShell folder on PATH.
set windows-shell := ["C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

# List recipes
default:
    @just --list

# Install the Python environment (Python 3.11, all dependency groups)
setup:
    uv sync

# Check local prerequisites (Docker, just, uv, Ollama, WSL memory cap, .env)
doctor:
    uv run python -m scripts.doctor

# Fill empty generated secrets in .env (creates it from .env.example); never prints values
gen-keys:
    uv run python -m scripts.gen_keys

# Create host folders that containers write to (see scripts/prepare_dirs.py)
prepare-dirs:
    uv run python -m scripts.prepare_dirs

# Start core + fhir (+ extra profiles, e.g. `just up rag`), wait until healthy
up *profiles: prepare-dirs
    docker compose --profile core --profile fhir {{prepend("--profile ", profiles)}} up -d --build --wait --wait-timeout 300

# Start every profile (needs more than the 10 GB WSL cap later on; see ADR-0003)
up-all: prepare-dirs
    docker compose --profile core --profile fhir --profile rag --profile voice --profile obs up -d --build --wait --wait-timeout 600

# Stop all services (data volumes are kept)
down:
    docker compose --profile "*" down

# Service status and health
ps:
    docker compose --profile "*" ps

# Service logs, e.g. `just logs litellm`
logs *args:
    docker compose --profile "*" logs --tail 200 {{args}}

# Memory per container and total against the 8 GB core budget
stats:
    uv run python -m scripts.stats

# Generate Synthea patients (seeded) and load them into HAPI FHIR; safe to re-run
fhir-load:
    uv run python -m scripts.fhir_load

# Register the app's gateway key with its budget and rate limit (idempotent)
gateway-keys:
    uv run python -m scripts.gateway_keys

# Inject or clear a fault, e.g. `just chaos primary-down on`
chaos fault state:
    uv run python -m scripts.chaos {{fault}} {{state}}

# ruff (lint + format check) and mypy
lint:
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy

# Auto-format and apply safe lint fixes
fmt:
    uv run ruff format .
    uv run ruff check --fix .

# Unit and integration tests (integration tests skip when the stack is down)
test *args:
    uv run pytest {{args}}

# Unit tests only: fast, no Docker, no network
test-unit *args:
    uv run pytest -m unit {{args}}

# Tests that call real free-tier provider APIs (rate limited; run on purpose)
test-live *args:
    uv run pytest -m live {{args}}

# Build the RAG corpus into data/corpus (`just ingest --offline` reuses the raw cache only)
ingest *args:
    uv run python -m retrieval.ingest.pipeline {{args}}

# Embed the corpus into the dense Qdrant collection (needs `just up rag`; `--recreate` rebuilds)
index *args:
    uv run python -m retrieval.dense {{args}}

# Contextual-retrieval prefixes from the local model (hours; resumable): `just contextual --limit 30`
contextual *args:
    uv run python -m retrieval.contextual {{args}}

# Precompute ColBERT document token vectors for reranking (resumable; data/index/colbert-*)
index-colbert *args:
    uv run python -m retrieval.colbert {{args}}

# Cited-answer evaluation on the 60-question subset (cached, resumable; free-tier budgets may stop it)
answers:
    uv run python -m evals.rag.answer_eval --system dense --system hybrid_colbert_ctx

# Qdrant vs pgvector on recall and latency (ADR-0007); needs `just up rag` and `just up vectorstore`
vectorstore:
    uv run python -m evals.rag.vectorstore_eval

# Drug-interaction graph: DDInter + RxNorm into Neo4j (needs `just up rag`; `--sources-only` skips Neo4j)
graph *args:
    uv run python -m retrieval.graph.build {{args}}

# Validate the golden Q&A set against the corpus (`just golden --expand` refreshes gold chunk ids)
golden *args:
    uv run python -m evals.golden.golden {{args}}

# Golden-set review sheet: `just golden-review make` or `just golden-review summary`
golden-review action="summary":
    uv run python -m evals.golden.review {{action}}

# Evaluation suites (`just eval privacy`, or all); reports go to evals/reports/
eval suite="all":
    uv run python -m evals.run {{suite}}

# Recompute the audit log hash chain; exit 1 and name the first broken row if tampered
audit-verify:
    uv run python -m scripts.audit_verify

# Apply pending SQL migrations to the clinscribe database (idempotent)
migrate:
    uv run python -m scripts.migrate

# Run a phase's exit gate, e.g. `just gate 1` (needs the stack; makes real LLM calls)
gate phase:
    uv run python -m scripts.gate {{phase}}

# Load tests with p50/p95 (Phase 6)
load:
    @echo "Load tests are not implemented until Phase 6."; exit 1

# Bearer token for a synthetic demo user (config/users.yaml), e.g. `just token dr-demo`
token user:
    uv run python -m apps.api.auth {{user}}

# Turn taking, barge-in and echo on the real LiveKit pipeline (simulated sound card; ~25 min, or --quick)
voice-turns *args:
    $env:VIRTUAL_ENV = $null; uv run --project voice python voice/turn_eval.py {{args}}

# Scribe from consultation audio, e.g. `just scribe 1617` (microphone, Enter to finish) or
# `just scribe 1617 --file consult.wav`; the draft then waits in the review UI (Scribe tab)
scribe patient *args:
    uv run --group voice python -m voice.scribe {{patient}} {{args}}

# Demo video (SPEC section 14), recorded live from a hidden Chrome: .artifacts/demo/clinscribe_demo.mp4
# Needs `just up rag`, the UI dev server and ffmpeg (not DEV_LOGIN); `--scenes title,results` for a subset.
# playwright drives the installed Chrome (no browser download); it is not a project dependency.
demo-video *args:
    uv run --with playwright==1.63.0 python -m scripts.demo_video {{args}}

# Voice agent in console mode: local microphone and speakers (Phase 4; needs `just up rag`).
# The first run downloads the turn-detector and VAD models (to HF_HOME on D:).
voice mode="console":
    $env:CLINSCRIBE_TOKEN = (uv run python -m apps.api.auth dr-demo); $env:VIRTUAL_ENV = $null; uv run --project voice python voice/agent_cascaded.py download-files *> $null; uv run --project voice python voice/agent_cascaded.py {{mode}}
