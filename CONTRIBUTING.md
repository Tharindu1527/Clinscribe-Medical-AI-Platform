# Contributing to ClinScribe

## Rules that are not negotiable

- Synthetic or public data only. Never add real patient data, not even in a test or a screenshot.
- No PHI reaches a model, a log or a trace before `privacy/deid`. Model calls go through the LiteLLM
  gateway (`llmops/gateway`) only; provider SDKs are banned outside it by a ruff rule.
- Clinical writes happen only through `fhir-mcp` `write_fhir` with an approval token.
- Every clinical claim cites a source chunk id; the guardrails reject the rest.
- Secrets live only in `.env` (git-ignored); never print, log or commit them.

## Workflow

1. Branch from `main`; `main` only accepts pull requests that pass `lint-unit` in CI.
2. Small commits with conventional messages (`feat:`, `fix:`, `test:`, `docs:`, `chore:`).
3. A change touching more than three files starts with a short plan.
4. Before asking for review: `just lint` and `just test` (with the stack up for integration tests),
   and the evaluation your change can affect (`just eval redteam`, `just eval rag`, ...).
5. Significant decisions get an ADR in `docs/adr/` (Context, Options, Decision, Consequences).
6. Record what changed, what is next and what is blocked in `docs/PROGRESS.md`.

## Adding things

- **A dependency:** one-line reason in `pyproject.toml`; prefer releases at least two weeks old; lock
  with `uv lock --upgrade-package <name>==<version>` so nothing else moves.
- **A prompt:** a new YAML in `prompts/` with `id`, `version`, `task`; map the task to an alias in
  `config/models.yaml`; bump the version for every change.
- **A guardrail rule:** `config/guardrails.yaml`, a unit test in `tests/unit/test_guardrails.py` and a
  red-team case in `evals/redteam/cases.yaml`.
- **A tool:** a typed contract in `agents/schemas.py`, the tool on an MCP server, an in-process unit
  test and a stdio/HTTP integration test.

## Layout

`apps/` (API, web UI) · `agents/` (graph, contracts, guardrails, lab) · `mcp_servers/` · `retrieval/` ·
`privacy/deid/` · `llmops/` (gateway, telemetry) · `prompts/` · `config/` · `evals/` · `tests/` ·
`finetune/` · `docs/` (ADRs, compliance, runbooks, postmortems).
