# ADR-0016: Durable drafts — Postgres checkpoints without PHI

Status: Proposed · Date: 2026-10-24

## Context

A Scribe draft waits at LangGraph's `interrupt()` until a doctor reviews it. The checkpointer was
LangGraph's in-memory saver, and the draft list a Python dict, so any API restart (every `just up`
rebuild, a crash, a deployment) silently dropped every draft awaiting review: in a clinic, the
doctor's consultation notes would vanish. This was an open question since Phase 3.

Making checkpoints durable raises a privacy question. The review step carried the patient's birth
date and family name (the two-identifier check), and since ADR-0015 the re-identified note, in the
resume payload, so a durable checkpointer would have stored them in Postgres, in every checkpoint
of the draft's history.

## Options

Storage:

1. **Keep the in-memory saver** and document the loss. Simple, and wrong for clinical work.
2. **LangGraph's Postgres checkpointer** (`langgraph-checkpoint-postgres`, MIT) in the existing
   `clinscribe` database, plus a small `drafts` table for the list and the outcome.
3. **A home-made draft table** holding the note and the review payload, outside LangGraph: loses
   LangGraph's replay and per-step history, and duplicates its state handling.

PHI in checkpoints:

- a. store it, encrypted (LangGraph's encrypted serializer; one more dependency and key);
- b. store it, and delete a draft's checkpoints when it ends: PHI at rest while the draft is open,
  and in every attempt's history after a refused write;
- c. **never put it in graph state**: pass it as LangGraph run context (`invoke(..., context=)`),
  which is given to the nodes of one run and never checkpointed.

## Decision

Option 2 with c, and the draft's checkpoints deleted when it ends.

- `langgraph-checkpoint-postgres==3.1.2` (August 2026; works with the pinned `langgraph-checkpoint`
  4.2.0; newer releases need 4.3) and its `psycopg-pool`. `just migrate` creates or updates
  LangGraph's tables as the owner and gives the `app` login DML on them; migration 003 adds
  `drafts` (no PHI: FHIR patient id, encounter id, author, status, resource id), where `app` may
  insert and update but never delete.
- The graph's commit node takes the identifiers and the resource from `WriteContext`, the run
  context; the resume payload carries only the decision and the approval token. A commit without
  identifiers refuses to write.
- The API checkpoints Scribe drafts only. Ask runs have nothing to resume, so they use a graph
  compiled without a checkpointer: no database writes per question.
- When a draft ends (written, rejected, or refused for good), the API records the outcome in
  `drafts` and deletes the draft's checkpoints. The audit log and FHIR keep the clinical record.

## Consequences

- A pending draft survives a restart: shown live (`tests/live/test_clinical_flow.py`: a draft made
  before `docker compose restart api` is listed and approved afterwards) and against Postgres
  without models (`tests/integration/test_durable_drafts.py`: another process and pool resume it).
- PHI stays out of the checkpoint tables: both tests scan what was stored for the draft and find the
  draft's text (positive control) but not the birth date or family name; the probe behind this
  design showed LangGraph keeps run context out of all three checkpoint tables.
- Data minimisation: after a draft ends only its outcome row remains; the de-identified transcript
  and note go with the checkpoints. Drafts nobody reviews stay until reviewed: a retention job for
  abandoned drafts is not built (DPIA).
- Lab results awaiting confirmation (`/v1/lab/*`) were still held in memory; a restart dropped
  them. Fixed 2026-10-27 (below).
- ADR-0015's caveat (the identified resource held in the review payload) no longer applies.

## Update 2026-10-27: lab results awaiting confirmation

They were the last clinical state in the API's memory: every `just up` rebuild dropped them, and
retention, erasure and access requests (ADR-0022) could not reach them. Now a `lab_results` table
(migration 005, `apps/api/labs.py`): the parsed result (preliminary Observations, flags, the
identity check's booleans; no name or birth date) is kept while it waits, and set to NULL when it
ends, since a confirmed result is in the FHIR record; the row keeps who, when, the outcome and the
Observations written. A confirmed result cannot be confirmed again (404). The API may insert and
update, never delete; the retention login ends results that wait too long or that an erasure
request covers. Tested on the stack: a result parsed before `docker compose restart api` is
confirmed after it; afterwards its row holds no values.

