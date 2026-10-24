# ADR-0015: Re-identification for the doctor's screen and the approved record

Status: Proposed · Date: 2026-10-24

## Context

SPEC §8: PHI is replaced with consistent surrogates (`PATIENT_1`), and "the mapping is encrypted
and only used to re-identify text in the doctor's own screen". That last part was never built.
Re-identification existed only as a library function (`Deidentifier.reidentify`) with a round-trip
test, and PROGRESS wrongly listed a doctor-only `/reidentify` as done in Phase 3. As a result:

- the doctor reviewed "PERSON_1 drove in from LOCATION_1" rather than the patient's own words;
- the approved note was written to FHIR in surrogate form, so the clinical record lost real dates
  and names ("since DATE_1"), and could only be read through the de-ID mapping, forever.

The design rule that matters is that no PHI reaches a model, a log or a trace before de-ID. The
doctor's screen and the clinical record (HAPI, the EHR) are where PHI belongs.

## Options

1. **Keep surrogates everywhere** (status quo). Safe, but the record is clinically degraded and
   depends on the mapping key.
2. **Re-identify on the screen only; keep the record in surrogate form** (SPEC read literally). The
   doctor would approve text that differs from what is stored, and the record problem remains.
3. **Re-identify on the screen and in the approved record; keep the model side surrogate-only.**

Who may call the de-ID service's re-identification route:

- a. open on the internal network: any service (guidelines-mcp, a compromised MCP server) could
  re-identify anything;
- b. any valid doctor token, checked by the de-ID service: a doctor could call it directly and
  skip the API's audit;
- c. **only the API**, with a key held by the API and the de-ID service alone
  (`DEID_REIDENTIFY_KEY`); the API checks the doctor role and audits.

## Decision

Option 3 with c.

- `POST /reidentify` on the de-ID service takes a batch of texts for one encounter and needs the
  `X-Reidentify-Key` header; without the key, with a wrong one, or when the service has none, it
  answers 403. Surrogates without a mapping (another encounter's) stay as they are.
- The API serves originals only on request (`?identified=true`) and only to doctors, on
  `POST /v1/ask`, `POST /v1/scribe/drafts` and `GET /v1/drafts/{id}`. Every call that restores
  anything is audited as `phi.reidentify`, with the context, the number of texts and the number of
  surrogates restored, never the text.
- On approval, the API re-identifies the note and signs the approval token over that exact resource;
  the graph writes the resource it is given, and fhir-mcp verifies the token as before. What the
  doctor read is what is stored.
- Edits typed on the identified view go to the record as the doctor wrote them, and are
  de-identified again (same encounter, so the same surrogates) before they go back into the graph:
  the note in graph state and the before/after edit pairs, future evaluation data, stay PHI-free.
- The review UI shows the originals and offers "Show what the AI saw" (surrogate text, read-only).
- Voice answers stay in surrogate form: re-identifying them would send originals to the text-to-
  speech vendor. Answers drawn from guidelines rarely contain patient identifiers.

## Consequences

- The FHIR record holds real names and dates, as an EHR must. Nothing changes for models, logs and
  traces: the leak test (gate b) still passes, and a live session with a synthetic name and town
  left 0 occurrences in 70 MB of container logs and the trace export. fhir-mcp's audit rows carry
  ids and hashes, not content.
- Like the two identifiers already were, the identified resource sits in the graph's review payload
  until the write. Today the checkpointer is in memory; a durable checkpointer (an open question)
  must encrypt or drop the review payload.
- A doctor's edit is re-de-identified with the same recognisers, so PHI they miss in the new
  wording would stay in the in-memory edit pair. Before edit pairs are stored as evaluation data,
  scan them with the leak-test scanner.
- One more secret to rotate (`docs/runbooks/operations.md`); only the API and the de-ID service
  restart.
- The demo video (recorded 2026-10-19) predates this: its draft shows surrogates.
- Tests: `tests/unit/test_reidentify.py` (route, client, API flow with a scripted model) and a live
  test in `tests/live/test_clinical_flow.py` (the model sees a surrogate, the doctor the name, the
  saved note holds the doctor's words, the edit pair none of them).
