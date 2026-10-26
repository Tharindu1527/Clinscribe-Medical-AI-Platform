# Audit log design

Implementation: `apps/api/audit.py`, migration `002` (Phase 1 task 8). Verify with `just audit-verify`.

- **Table:** `audit_log` with an identity `seq`, timestamp, actor, role, action, resource type and id,
  encounter id, model, prompt version, trace id, `details` (JSON, never PHI), `prev_hash`, `hash`.
- **Chain:** `hash = HMAC-SHA-256(AUDIT_CHAIN_KEY, prev_hash + canonical JSON of the row)`; the first
  row chains from 32 zero bytes. `verify()` recomputes the chain and names the first broken row.
- **Append-only:** triggers refuse UPDATE, DELETE and TRUNCATE for every role, the owner included;
  the application role has INSERT and SELECT only. An advisory lock serialises appends, so chain order
  is commit order (tested with concurrent writers).
- **Recorded actions:** `ask`, `draft.create`, `draft.approve` / `draft.edit` / `draft.reject`,
  `fhir.read` (every patient-context read, with the user), `fhir.write`, `fhir.write.duplicate`
  (a replayed approval), `fhir.write.refused` (with the reason), `lab.parse` (with the format: pdf or hl7v2), `lab.confirm`,
  `phi.reidentify` (a doctor was shown originals, or a note was re-identified for the record:
  context, number of texts and of surrogates restored, never the text; ADR-0015), `voice.session`
  (a doctor opened a voice room) and `voice.delegate` (the voice agent was given a short token to
  ask as that doctor; ADR-0019), and the Phase 1
  pipeline endpoint.
- **Who can read it:** `GET /v1/audit` for the admin and operator roles; doctors cannot.
- **Answers SPEC user story 5:** who viewed or changed a record, when, and with which model and prompt
  version.
- **Limits:** the HMAC key and the database live on the same host, so an attacker with both could
  rebuild the chain. A real deployment anchors the head hash externally (for example a WORM store) and
  keeps the key in a secrets manager.
