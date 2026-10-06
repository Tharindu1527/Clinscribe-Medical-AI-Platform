# ADR-0004: De-ID v1 — names and places from context, clinical terms left intact

Status: Accepted · Date: 2026-10-06

## Context

The Phase 1 leak test passed (no PHI in traces, logs or stores), but 2 of 66 seeded values still reached
the LLM: invented town names that spaCy missed. CLAUDE.md requires that no PHI reaches an LLM.
De-ID v0 recall was 0.95 for names and 0.75 for places on the seeded set.

A new over-redaction measure (80 PHI-free clinical sentences, `evals/privacy/clinical_negatives.py`)
showed a second problem: v0 altered **17.5%** of them. Eponyms became names ("PERSON_1 lymphoma" for
Hodgkin lymphoma, "A PERSON_1 catheter" for Foley), place-named diseases became places ("LOCATION_1
virus" for West Nile), and drug brands were redacted. That damages the clinical meaning the LLM and the
doctor see.

## Options

1. **Larger spaCy model (`en_core_web_lg`)** alone. Measured (same evaluation): held-out names 1.000 but
   places 0.650 (worse than md), 1 of 80 sentences over-redacted ("Glasgow Coma Scale"), 702 MB peak
   memory vs 334 MB, 401 MB download vs 33 MB.
2. **Name and place gazetteers** (Census surnames, first names, places). Faker's invented towns
   ("Jacquelineland") are in no gazetteer, and common surnames (Brown, White, Hope) would over-redact.
3. **Context cues plus a clinical-term filter** on top of spaCy `md`: cue patterns for names
   (titles, relation words, a name before MRN/DOB) and places (`City, ST`, "lives in", "referred …
   from"); an eponym rule (a capitalised word followed by a clinical head noun is a term) and an
   RxNorm-based lexicon of drug and department names (person names removed).
4. **Fine-tuned NER (Phase 5 LoRA)** now. The right long-term answer, but it needs labelled clinical
   speech and is scheduled for Phase 5.

## Decision

Option 3, keeping spaCy `en_core_web_md`.

- Cue patterns run as a second Presidio recogniser (`clinscribe-context`, score 0.88: above spaCy's 0.85,
  below exact formats at 0.9).
- The eponym rule applies only to spaCy's own guesses; cue matches are never overridden by it, so
  "Dr. Parkinson" stays redacted. One modifier from a closed list may sit before the head noun
  ("Rocky Mountain spotted fever"); an open slot would turn "John Smith has fever" into a term.
- The lexicon (`privacy/deid/resources/clinical_lexicon.txt`, 19,079 terms from RxNorm via RxNav, built
  by `scripts/fetch_lexicons.py`) suppresses only exact single-span matches.

Results (`evals/reports/privacy/deid_v1_en_core_web_md.md`):

| | v0 | v1 seeded | v1 held out (no gate) |
|---|---|---|---|
| Names | 0.950 | 1.000 | 0.973 |
| Places | 0.750 | 1.000 | 0.850 |
| Structured types (15) | 1.000 | 1.000 | 1.000 |
| Over-redaction (80 clinical sentences) | 17.5% | 0.0% | — |

## Consequences

- The seeded set was used to design the cues, so its 1.000 is optimistic. The held-out set (new
  phrasings and seed, frozen: never used for tuning) shows the honest picture: misses remain for
  places without a cue ("originally from X", "works in X", "moved here from X") and for a second name
  in a list ("with A and B"). Closing these is Phase 5 (fine-tuned NER) or a new held-out set per change.
- Known gap: a lexicon entry that is also an uncommon first name (e.g. the brand "Allegra") is not
  redacted when it appears alone with no cue. Cued mentions ("Mrs. Allegra Smith") are redacted.
- Over-redaction is now gated (≤ 1%), so future recall work cannot silently damage clinical text.
- `en_core_web_lg` stays available via `DEID_SPACY_MODEL` for future comparisons; its report is kept.
- The lexicon must be rebuilt when RxNorm changes (`uv run python -m scripts.fetch_lexicons`).
