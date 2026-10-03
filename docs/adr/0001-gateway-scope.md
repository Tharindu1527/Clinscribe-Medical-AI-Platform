# ADR-0001: What goes through the LLM gateway

Status: Accepted · Date: 2026-10-04

## Context

CLAUDE.md requires every LLM call to go through the LiteLLM gateway (`llmops/gateway`). The gateway is
the one place for failover, budgets, cost logging and a final redaction check. Some model calls do not
fit that path:

- Late chunking needs token-level vectors from a long-context embedding model. An OpenAI-compatible
  embeddings endpoint returns only pooled vectors, so it cannot serve this through the gateway.
- The cross-encoder reranker, ColBERT and the de-identification NER model are small local encoders.
  They do not generate text and have no provider behind them.
- RAGAS and DeepEval create their own provider clients for judge models unless they are configured otherwise.

## Options

1. **Everything through the gateway.** Host every local encoder behind an OpenAI-compatible server
   (for example Infinity or TEI) and register it in LiteLLM. Uniform, but late chunking is still
   impossible, and each extra server costs memory under the 10 GB WSL cap.
2. **Generation and hosted embeddings through the gateway; local encoders in-process.** Evaluation
   libraries are pointed at the gateway's OpenAI-compatible base URL.
3. **Evaluation libraries call providers directly.** Simpler set-up, but it bypasses budgets, failover and
   cost logs, and puts provider keys into a second code path.

## Decision

Option 2.

- All text generation and all hosted (API) embeddings go through the gateway via `llmops.gateway.client`.
- Local encoder models (embeddings for late chunking, cross-encoder, ColBERT, NER) run in-process and
  accept only de-identified text (the `DeidentifiedText` type from `privacy/deid`).
- RAGAS and DeepEval judge models are configured with the gateway URL and an app key.
- The only direct provider SDK use is the speech-to-speech plugin (`voice/agent_s2s.py`, Gemini Live),
  justified in its own ADR in Phase 4.
- Enforcement: ruff `TID251` bans provider SDK imports (`openai`, `anthropic`, `groq`, `google.genai`,
  `google.generativeai`, `litellm`) everywhere except `llmops/gateway/**` and `voice/agent_s2s.py`;
  `tests/unit/test_banned_imports.py` proves the rule fires.

## Consequences

- Local encoder latency and errors do not appear in gateway logs, so they get their own OpenTelemetry spans.
- Local models are pinned by name and revision in `config/models.yaml` so results are reproducible.
- Evaluation judge calls share the free-tier quotas and budgets with the app; daily runs use small subsets.
- A new provider SDK needs an edit to the banned list, and the rule is visible in code review.
