# ADR-0022: Retention limits and GDPR erasure as audited operator jobs

Status: Proposed · Date: 2026-10-26

## Context

SPEC §8 maps GDPR to "data minimisation, retention limits, erasure endpoint"; the DPIA listed
both as gaps (no erasure, no enforced retention). What ClinScribe itself stores about a patient:

| Store | Content | PHI |
|---|---|---|
| `deid_mappings` | surrogate ↔ original value per encounter, Fernet-encrypted | yes (encrypted): the only place originals are kept |
| LangGraph checkpoint tables | a waiting draft's de-identified transcript and note | surrogates only |
| `drafts` | draft id, FHIR patient id, encounter, author, outcome | pseudonymous ids |
| `audit_log` | who did what, ids and counts | pseudonymous ids |
| FHIR (HAPI) | approved notes and lab values | yes: the clinical record |

Two facts shape the design. The `app` login used by the API and the de-ID service may add and read
mappings but never delete them (Phase 1). And surrogate numbers count an encounter's existing
rows, so deleting part of an encounter's mapping would give a new value the number of an old one.

While mapping this out, one finding: the voice agent sent every question as encounter
`voice-session`, so all voice sessions, whoever spoke, shared one mapping that grew without end and
could never become idle.

## Options

1. **An admin endpoint in the API** (SPEC's wording): the API would need DELETE on the mapping, the
   one table it cannot damage today.
2. **Operator commands with their own login**: a `retention` login that may delete mappings and
   checkpoints, end drafts and append to the audit log; run on the host by an operator or a
   scheduler, dry run by default.
3. **Crypto-shredding with a key per patient**: deleting the key erases the originals at once,
   but it needs key management per patient, and the mapping is per encounter, not per patient.

## Decision

Option 2 (`scripts/retention.py`, `just retention`, `just erase`).

- **Retention** (`config/retention.yaml`): a draft nobody reviewed in 14 days ends as "expired"
  and its saved state is deleted; an encounter's mapping is deleted 30 days after it last gained a
  value, except while a draft for that encounter still waits. Approved records keep their
  originals in FHIR, so the mapping is not needed afterwards.
- **Erasure** (`just erase <patient> --request <ticket> --by <admin>`): ends that patient's waiting
  drafts as "erased" and deletes the mapping of every encounter their drafts used, whatever its
  age. The request reference must be a ticket id (no free text, so no names in the log); `--by`
  must be an admin in `config/users.yaml`.
- Mappings are always deleted as whole encounters, under the same per-encounter lock the de-ID
  service takes. Retention re-checks idleness under that lock, so an encounter used again after
  the plan keeps its mapping.
- Each applied run appends one audit row (`retention.run` or `gdpr.erasure`) with counts only, in
  the same transaction as the deletions: no deletion without its audit row. A dry run changes and
  records nothing.
- Kept, with the reason recorded here and in the DPIA: the audit log (append-only;
  accountability, GDPR Art. 5(2), and the AI Act's logs for high-risk systems, kept at least six
  months; no deletion is implemented), the drafts list (pseudonymous outcome rows, which the audit
  log refers to), and the FHIR record (its retention is the EHR controller's; an erasure request
  for the record goes there).
- Voice: one encounter per session (`voice-<random>`), so each session's mapping is its own and
  expires with it.

## Consequences

- Measured on the real Postgres (`tests/integration/test_retention.py`, 8 tests): a stale draft
  expires and its state and mapping go; a mapping whose draft still waits stays; an ended draft's
  row stays; an encounter used again after the plan keeps its mapping; erasure removes one
  patient's waiting draft and the mappings of both their encounters, leaves another patient's
  untouched, and afterwards nothing can be re-identified; a failing audit write rolls the
  deletions back; requests with free text, a non-admin or a malformed id are refused; the
  retention login cannot delete audit rows or edit mappings, and the app login still cannot delete
  mappings. Removing either safeguard (the re-check, the waiting-draft exception) fails a test.
- Not an API endpoint: an admin cannot erase from the review UI. A scheduler must run
  `just retention --apply` (daily; operations runbook); nothing enforces the limits otherwise.
- Not reached: lab values pending confirmation (the API's memory only, gone at restart),
  de-identified traces (the local trace file and Langfuse Cloud keep their own retention), and the
  gateway's spend logs (no prompt text).
- The SPEC says "erasure endpoint"; this is a command. The reason is the API's least privilege
  over the mapping, which stays as it was.

## Update 2026-10-27: access requests (GDPR Art. 15)

The DPIA still listed "no access/export command". `just access-report <patient> --request <ticket>
--by <admin>` (`scripts/retention.py access`, the same login and request checks as erasure)
writes a copy of what ClinScribe holds about one patient to `.artifacts/subject-access/`
(git-ignored): the drafts list; a waiting draft's transcript and note with the originals put back
from the mapping; the mapping's identifiers (type, surrogate, original); the audit rows that name
the patient, their drafts or encounters (who read or changed what, when); and the purposes,
recipients and retention limits. The copy holds PHI, so it is written to a file and never
printed; the operator hands it over securely and deletes it. Each request appends `gdpr.access`
with counts and the ticket id only, before the file is written, so a failed write still shows
as an attempt. The clinical record itself is the EHR's: the copy says so and points there.

Tested on the real Postgres (`tests/integration/test_retention.py`): a draft made by the graph
whose saved transcript and note held a surrogate comes back with the original; the copy holds the
patient's two encounters' originals and their audit row, and nothing of another patient's; the
audit row holds counts, not data; the chain verifies.

