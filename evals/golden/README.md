# Golden Q&A set (v1)

`golden_v1.jsonl`: 235 questions for retrieval and answer evaluation (Phase 2 task 3).

- **209 answerable**, about 40 per clinical area (hypertension, diabetes, anticoagulation, asthma/COPD,
  infections), drawn from WHO guidelines (43), FDA labels (81) and PMC reviews (85).
- **26 unanswerable** (11%): in-scope questions about drugs that do not appear anywhere in the corpus.
  The validator checks that their `absent_terms` really are absent.
- Question types: recommendation, fact, dose, adverse effect, contraindication, interaction.

## How it was made

1. `python -m evals.golden.candidates` drew a seeded, stratified sample of corpus chunks that state
   something checkable: a number, dose, recommendation or interaction.
2. Claude (claude-opus-5-5, 2026-10-06) read each chunk and wrote a doctor-style question in its own
   words. The answer is an **exact quote** from the chunk. Off-topic, garbled and reference-list
   chunks were skipped, as was one outdated label statement (rivaroxaban "no reversal agent").
3. `just golden --expand` sets `gold_chunk_ids` to every chunk that contains the quote. This picks
   up the overlapping neighbour chunk, and class-wide label text such as the DOAC warning in
   antiphospholipid syndrome. One false match, a lisinopril quote that also occurred in the losartan
   label, was fixed by quoting more of the sentence.
4. `just golden` validates the set:
   - every gold chunk exists and contains the quote;
   - no question shares 6+ consecutive words with its source (copied wording would favour keyword
     search);
   - absent terms are absent;
   - the quotas are met.

## Human review

A stratified 20% sample (49 items, every area and both answerable and unanswerable) is in
`review/review_v1.csv`, created with `just golden-review make`. A reviewer fills in `verdict`
(ok / fix / reject), `notes`, `reviewer` and `reviewed_on`. `just golden-review summary` checks the
sheet. The filled sheet stays in the repo as the record of who reviewed what.

The drafter is a language model, not a clinician. Each quote is verifiably in its source, but whether
the question is clinically sensible and fully answered by the quote needs the human check.

## Licences

Quotes and the passages in the review sheet are short excerpts of public sources, each with its
URL. They keep their source licences: WHO CC BY-NC-SA 3.0 IGO, PMC articles CC BY / CC0, openFDA CC0
(see `data/LICENSES.md`).
