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

# Start core + fhir (+ extra profiles, e.g. `just up rag`), wait until healthy
up *profiles:
    docker compose --profile core --profile fhir {{prepend("--profile ", profiles)}} up -d --build --wait --wait-timeout 300

# Start every profile (needs more than the 10 GB WSL cap later on; see ADR-0003)
up-all:
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
