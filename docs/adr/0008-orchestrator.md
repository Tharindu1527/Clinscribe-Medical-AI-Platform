# ADR-0008: Agent orchestrator — LangGraph

Status: Proposed · Date: 2026-10-13

## Context

SPEC §5 asks for one agent graph with explicit state, a human-approval stop before any clinical write,
validated structured outputs and replay, and for LangGraph to be compared with Pydantic AI and the
OpenAI Agents SDK so the choice is justified. The graph is built (`agents/graph.py`): intake → router →
fast or agentic Ask path → guardrails with one retry → note writer → guardrails → `interrupt()` for the
doctor → commit through fhir-mcp. Every model call goes through the LiteLLM gateway (CLAUDE.md).

## Options

1. **LangGraph 1.2** (chosen and built).
2. **Pydantic AI 2.51** (`pydantic-ai-slim`).
3. **OpenAI Agents SDK 0.22** (`openai-agents`).

Measured on 2026-10-13 in a throwaway environment on D: (each package alone, Python 3.11):

| | LangGraph | Pydantic AI | OpenAI Agents SDK |
|---|---|---|---|
| Installed packages (incl. dependencies) | 40 | 19 | 41 |
| Cold first import (one run, includes bytecode compile) | 7.4 s | 3.8 s | 6.1 s |
| Human approval in the installed code | `interrupt()` anywhere in a node; resume with `Command(resume=...)` | tools with `requires_approval`; `DeferredToolRequests` / `DeferredToolResults` | tools with `needs_approval`; run `interruptions`; `RunState` serialisable (`to_json`) |
| Durable state between steps | checkpointer per step (memory, SQLite, Postgres); `get_state_history` replay | serialisable message history + deferred results | `RunState` JSON |
| Licence | MIT | MIT | MIT |

Not done: the same task built three times. The SPEC's "compare on one task" is reduced to the table
above (footprint, the approval mechanism each library actually ships, state model); a timed side-by-side
on the Ask path is left for later and would not change the decision below unless one of the
alternatives were clearly faster at equal safety.

## Decision

Keep LangGraph. All three can pause for approval, but only LangGraph pauses on *graph state* rather
than on a tool call: the doctor reviews a whole draft (statements, unsupported claims, removed
statements) before the write node runs, the pause survives a new graph instance through the
checkpointer (tested: `test_review_survives_a_new_graph_instance_with_the_same_checkpointer`), and every
step can be replayed from `get_state_history`, which the operator stories in SPEC §2 need. The approval
in Pydantic AI and the Agents SDK is attached to a tool call, so the review would have to be modelled as
"approve this write_fhir call", which hides the draft-level review the EU AI Act oversight story needs.

## Consequences

- LangGraph is the heaviest import of the three (40 packages); acceptable in the API image (0.97 GB).
- The OpenAI Agents SDK's import name `agents` clashes with this repo's `agents/` package; any later
  comparison runs in an isolated project (PROGRESS open question).
- Pending drafts use the in-memory checkpointer today; a Postgres checkpointer
  (`langgraph-checkpoint-postgres`) is the drop-in when drafts must survive an API restart.
- Pydantic AI's typed outputs are attractive; ClinScribe gets the same effect from strict Pydantic
  contracts (`agents/schemas.py`) re-validated in code.
