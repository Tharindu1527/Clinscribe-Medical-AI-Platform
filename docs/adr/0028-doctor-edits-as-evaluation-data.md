# ADR-0028: Keep doctors' edits as before/after pairs for evaluation

Status: Proposed · Date: 2026-10-28

## Context

SPEC section 5: "Doctor edits are saved as before/after pairs, which become new evaluation data."
The graph built the pair (`commit` returns `edit_pair`, the AI draft and the note as approved),
the API returned it once in the review response, and nothing stored it: every edit was lost, and
the note writer's evaluation (`evals/agents/note_quality.py`) could only use ACI-Bench references.

Two problems turned up in the review path on the way:

- **An edit typed on the AI's view went into the graph as typed.** Only edits made on the
  re-identified view were de-identified; the review UI locks the surrogate view, but the API
  accepted edits from it, so a name a doctor typed there would have reached the checkpoint and the
  pair.
- **Unchanged statements were de-identified a second time.** On the re-identified view every
  statement goes back through de-ID on approval, and with the fine-tuned tagger (ADR-0014) the
  untouched "Patient has been really thirsty for about three weeks." became "PERSON_2 has been ...".
  Found on the first live pair: one statement edited, three counted as edited. The record was
  unaffected (it holds the doctor's words); the graph's copy, the pair and the mapping were.

## Options

1. **Store pairs in Postgres** (`edit_pairs`), in the surrogate form the graph works on, and export
   them as evaluation data after a PHI scan.
2. Keep them in the audit log: append-only, kept for years, never deleted; clinical text does not
   belong there (audit design: counts and ids only).
3. Write them to files from the API: no erasure, no access copy, no transactions.

## Decision

Option 1.

- **Review path** (`apps/api/clinical.py`): the edits reach the graph in surrogate form on either
  view, and a statement the doctor left as shown keeps the model's text (compared with what the
  doctor saw; on the identified view that comparison re-identifies the draft once, audited as
  `phi.reidentify`, context `review`). Only changed statements go through de-ID again.
- **Store** (`apps/api/edits.py`, migration 006): a pair per approved, edited draft: draft id,
  reviewer, prompt version, model, the AI draft and the approved note (both de-identified). The
  `app` login inserts and reads; only the `retention` login deletes. `draft.edit` audits
  `edit_pair_kept`.
- **Retention, erasure, access** (`scripts/retention.py`, ADR-0022): pairs are deleted after
  `edit_pairs_days` (365, a default to confirm with the data protection officer) and by an erasure
  request for the patient (found through the draft); the access copy lists them, re-identified
  while the encounter's mapping is kept.
- **Export** (`evals/agents/edit_pairs.py`, `just edit-pairs`): every statement of both sides is
  scanned with the de-ID engine's spaCy rules; a pair where they would replace anything is
  withheld. The rest go to `data/edit_pairs/edit_pairs.jsonl` (git-ignored) without the reviewer,
  with what changed per statement (unchanged, edited, removed, added; per section). The script
  prints counts only. The spaCy rules rather than the service's recogniser: the same engine finds
  nothing new in text it has just de-identified, and the tagger took "Patient" at the start of a
  sentence for a name, which withheld the first real pair.

## Consequences

- Evidence: unit tests for the change counts, the scan (a fake and the real spaCy engine: a typed
  name withheld, a surrogate kept), an edit typed on the AI's view stored in surrogate form, an
  over-redacting de-identifier that no longer touches unchanged statements, and no pair without
  an edit; integration tests on the real Postgres for retention, erasure, access and the logins'
  rights; the live clinical-flow test checks the stored pair holds the doctor's words and no name.
  The first live pair counted 3 edited statements before the fix and 1 after (7 unchanged).
- The only pairs so far come from tests; nothing is measured from them yet. The intended use is
  the note writer's evaluation: statements doctors remove or rewrite, by section and prompt
  version.
- The pairs are pseudonymous, not anonymous: the draft id links them to the patient until the
  pair is deleted, and the surrogates can be reversed while the encounter's mapping exists (30
  days). Hence the erasure and access coverage, and the retention limit.
- The scan's spaCy rules miss some names that have no cue around them ("Morgan Ellis is thirsty."
  passes; "Mr Morgan Ellis" and "Jane Smith reports chest pain." do not): it is a second opinion
  after the service's de-ID, not a guarantee. Review exported rows before they leave the machine.
- The tagger's over-redaction of "Patient" also affects what it de-identifies elsewhere (a
  doctor's edit, an Ask question starting with "Patient"); it is the class of error ADR-0014
  measured (1 of 40 PHI-free sentences) and is not changed here.
