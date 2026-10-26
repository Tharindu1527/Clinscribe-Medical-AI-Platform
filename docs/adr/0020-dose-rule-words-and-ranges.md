# ADR-0020: The dose rule reads doses in words, and ranges need a separator

Status: Proposed · Date: 2026-10-26

## Context

The dose rule (SPEC §5: "any dose statement needs a source"; `config/guardrails.yaml`) reads a dose
as a number in digits followed by a unit, and accepts a sentence's dose only if a cited source, or
for a note the cited transcript turn, has the same number and unit. Spoken units were added on
2026-10-18 ("500 milligrams"). Numbers in words were not, and the note-quality evaluation
(`evals/reports/agents/note_quality.md`) showed what that costs. In ACI-Bench D2N085 the doctor
says "I'm going to prescribe oxycodone five milligrams every six to eight hours"; the note writer
wrote "5 mg", the rule found no "5 mg" in the turn and removed the statement, so the draft lost the
opioid prescription the doctor had just dictated. In D2N077 ("fifty milligrams of ultram") the
first draft's "50 mg" was flagged, the note writer retried, and the retry left out the thumb
spica brace from the plan. The same gap works the other way: a sentence
that says "ten milligrams" contains no dose the rule can see, so an unsourced dose written in
words passed every check.

A second defect in the same pattern: the range part made its separator optional, so "N = 275
5 mg" read as a range from 275 to 5 mg, and "2 500 mg every 12 hours" (a table row number, then the
dose) as 2 mg and 500 mg.

## Options

1. Leave the rule as it is; rely on speech recognition writing numerals (`numerals=true` is set for
   live Scribe). Transcripts from other sources (ACI-Bench, a typed note) still lose doses.
2. Turn every number word into digits before matching. Simple, but "take two 500 mg tablets"
   would read as a 2 to 500 mg range, and counts become doses.
3. **Turn number words into digits only where a dose then reads** (a unit follows, or "to" and the
   end of a range), skip words followed by a number ("two 500 mg tablets"), and require "-", "to"
   or "–" between the two ends of a range.

## Decision

Option 3, as guardrails v2 (`config/guardrails.yaml` version "2", `Guardrails.numerals` and
`words_to_number` in `agents/guardrails.py`): zero to nineteen, the tens, hundred and thousand,
"and", and "point" with single digits after it ("two point five" → 2.5). Words that do not form
one number ("five two") are left alone. Both sides use it, the sentence and its sources.

## Consequences

- Measured with no model calls. Red-team suite 67/67 with two new cases: an answer saying "ten
  milligrams" with a source that says 2 to 5 mg (dose-16), and a note whose turn says "five hundred
  milligrams" while the plan raises it to "one thousand milligrams" (note-07). With v1 rules in
  the system and v2 as the checker exactly those two fail; on note-07 v1 removed the correct
  statement (500 mg, said in words) and kept the invented increase. Negative control unchanged in
  kind (23/67 with the rules off).
- Corpus (8,104 chunks): v2 reads 2 dose pairs that v1 did not and drops 109 that v1 read, in 55
  chunks. Every dropped pair seen was a table artefact (row numbers, days of treatment, trial arm
  sizes, body weights) that could have "supported" an invented dose such as 275 mg. Stored Phase 2
  answers (325 cited sentences): no verdict changes.
- Not covered: fractions in words ("half a milligram"), "a milligram", numbers split by PDF
  extraction ("2 . 5 mg"), and number words in other languages.
