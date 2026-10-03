# ADR-0003: Docker Compose profiles and memory budget

Status: Accepted · Date: 2026-10-04

## Context

The dev machine has 16 GB RAM, WSL2 capped at 10 GB, and an RTX 3050 Laptop GPU with 4 GB VRAM.
The full system (FHIR server, gateway, de-ID, vector store, graph database, voice stack, dashboards)
does not fit in 10 GB at once. Each phase only needs part of it, and SPEC section 14 still asks for
one command that starts the full stack.

## Options

1. **One flat Compose file, everything always on.** Simple, but it does not fit in memory.
2. **Compose profiles** so each phase starts only what it needs, with a memory limit on every service.
3. **Several Compose files** combined with `-f`. Works, but it is harder to read and easier to get out of step.

## Decision

Option 2. Every service has a `mem_limit`, a healthcheck and one profile:

| Profile | Services | Estimated RAM |
|---|---|---|
| core | postgres, otel-collector, litellm, deid, api | ~3.0 GB |
| fhir | hapi-fhir (JVM heap capped) | ~2.0 GB |
| rag | qdrant, neo4j | ~3.5 GB including local encoders in api |
| voice | livekit-server, voice-agent, web | ~1.7 GB |
| obs | prometheus, grafana | ~0.4 GB |
| tools | synthea (one-shot generator) | ~1.0 GB while running |

`just up` starts core + fhir (~5.0 GB, target ≤ 8 GB). `just up rag` (etc.) adds profiles.
Ollama runs on Windows, outside the WSL cap, using the GPU. vLLM is not used.

## Consequences

- These numbers are estimates. Phase 1 task 3 measures them with `just stats` and updates this ADR.
- core + fhir + rag + voice is about 10.2 GB, above the cap. Before the Phase 4 demo, choose between
  raising the cap to 12 GB, a smaller HAPI heap, or leaving out services the demo does not need.
- "One command for the full stack" (SPEC section 14) becomes `just up-all`, documented with its memory need.
- Services must not assume other profiles are running: integration tests check which profile they need.
