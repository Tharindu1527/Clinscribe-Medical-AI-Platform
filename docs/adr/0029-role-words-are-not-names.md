# ADR-0029: A role word alone is not a name

Status: Proposed · Date: 2026-10-28

## Context

Building ADR-0028, the first live edit pair showed the fine-tuned tagger (ADR-0014, the local
de-ID recogniser behind `DEID_NER=tagger`) replacing "Patient" at the start of a note sentence:
"Patient has been really thirsty for about three weeks." became "PERSON_2 has been ...". The
earlier PHI-free sets did not show it: PHI-free v1's one such sentence ("Patient reports chest pain
on exertion relieved by rest.") was left alone, and v2 has none. Doctors' edits, Ask questions and
note statements are written like this. A replaced role word changes no record (the API keeps the
doctor's words for FHIR), but it damages what the models and the evaluation data see, and puts a
meaningless entry in the encounter's mapping.

## Options

1. Retrain the tagger with role-word sentences: a Colab round, new frozen sets, and the error class
   may return elsewhere.
2. **Drop a model's guess that is only a role word**, as clinical terms are already dropped
   (de-ID v1, `privacy/deid/lexicon.py`).
3. Leave it and document it.

## Decision

Option 2 (`privacy/deid/engine.py` `ROLE_WORDS`, in `_not_phi`): a PERSON or LOCATION span from a
model (spaCy or the tagger) whose text is exactly a role word in care ("patient", "nurse", "wife",
"son", ...; a possessive "'s" is ignored) is not PHI. Two limits keep names safe:

- only a span that is the role word alone: in "Patient Jane Smith reports chest pain." the span is
  longer, so the name is still replaced;
- not after a cue: cue-based matches ("Mr Son", "Dr Child") are never filtered, since role words
  are also surnames.

Measured before and after on a set written for it and frozen before any engine ran on it
(`evals/privacy/clinical_negatives.py` `SENTENCES_V3`: 40 note-style PHI-free sentences with role
words; `ROLE_NAMES`: 10 with a synthetic name next to a role word), and on every earlier set
(`evals/privacy/role_words.py`, `evals/reports/privacy/role_words.md`):

| engine | filter | PHI-free v3 altered | names next to a role word replaced | PHI-free v1 / v2 altered | names / places held-out v3 |
|---|---|---|---|---|---|
| tagger | off | **16/40** | 10/10 | 0/80 / 1/40 | 90/90 / 50/50 |
| tagger | on | **0/40** | 10/10 | 0/80 / 1/40 | 90/90 / 50/50 |
| spaCy | off and on | 0/40 | 10/10 | 0/80 / 3/40 | 90/90 / 42/50 |

## Consequences

- The tagger altered 16 of the 40 sentences without the filter (10 of the 15 that start with
  "Patient", and the 6 that start with "Mother", "Wife", "Husband", "Daughter", "Son" or
  "Registrar") and none with it; recall on every earlier set is unchanged for both engines. The set was written to
  target this error after seeing it once, so it shows the filter removes it, not how common it is
  in real notes.
- A real surname that is also a role word ("Son", "Child") is no longer replaced when a model
  guesses it alone with no cue around it; after "Mr", "Dr" or a relation cue it still is.
- CI covers the rule with a fake recogniser that takes every first word for a name
  (`tests/unit/test_deid_roles.py`), including a control with the filter off; the tagger itself
  is measured locally, as in ADR-0014.
- Gate b (PHI leak test) re-run on the rebuilt service: see PROGRESS.
