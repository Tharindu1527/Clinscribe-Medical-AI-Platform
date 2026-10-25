# ADR-0018: Ground the question's subject before and after answering

Status: Proposed · Date: 2026-10-25

## Context

The ADR-0017 prompt trial produced a wrong-drug answer: asked about mazdutide, which the corpus
does not cover, the model answered with three sentences from the Ozempic (semaglutide) label. Every
sentence was faithful to its cited source, so the citation checks, the dose rule and the evaluation
judge's faithfulness all passed it; only the abstention metric caught it. The production prompt
abstained on that question, but nothing in the system guarantees it: whether a drug the clinician
asks about is the drug the sources describe was left to the model. SPEC §8 lists "hallucinated drug
fact" as the first patient-safety hazard.

## Options

1. **Leave it to the prompt** (status quo): the generator abstains when the sources do not answer.
2. **Unseen term, before answering**: if the question uses a word that no source ever uses (and
   that is not common English), no source can be about it, so abstain at once.
3. **Drug grounding, after answering**: every drug the question names (DDInter + RxNorm lexicon,
   with aliases and brands) must be named in at least one cited source.
4. **A model-based check** that the answer is about the question's subject: one more model call.

Options 2 and 3 were measured offline (`evals/rag/drug_grounding.py`,
`evals/reports/rag/drug_grounding.md`, no LLM calls), with the code that now runs in production:

| Check | Answerable questions blocked | Unanswerable caught | Notes |
|---|---|---|---|
| 2, word the corpus never uses | 5 of 209 | 26 of 26 | ordinary words: tighter, paused, fallen, vapour, nebulised |
| 2, and not common English (spaCy vectors) | 1 of 209 | 25 of 26 | nebulised (UK spelling); fenoldopam is missed (has a vector) |
| 2, and UK/US spellings folded | **0 of 209** | **25 of 26** | the fold was added after seeing "nebulised" |
| 3, on 185 stored answers (4 systems) | 0 | 0 | no answer in the stored runs cites a source missing the question's drug |

Caveats: the unanswerable golden questions were built as "a drug absent from the corpus", so the
catch rate is optimistic; the false blocks on answerable questions are the honest measure.

## Decision

Options 2 and 3, as deterministic checks in `retrieval/grounding.py`, served by guidelines-mcp's
new `check_grounding` tool (it holds the corpus, the lexicon and spaCy's vocabulary; it
de-identifies the question again, like `search_guidelines`; de-ID surrogates never count).

- The router runs check 2: a question naming an unseen term ends abstained, before any search or
  model call, and the API returns the term (`unseen_terms`), so the UI and the voice agent can say
  "no source mentions mazdutide" — also how a misheard drug name surfaces in voice.
- The answer guardrail runs check 3: a missing drug is a violation (`drug_not_in_sources`), handled
  like the others: one retry with the violation attached, then the safe reply.

## Consequences

- The mazdutide failure cannot recur through either path: red-team cases `subject-01` (abstains
  before any model call) and `subject-02` (an apixaban question answered from a warfarin chunk ends
  in the safe reply); both fail with the checks off (`--control`). Red-team 65/65.
- Cost: two `check_grounding` calls per answered question, p50 109 / p95 214 ms each (an MCP session
  and a de-ID round trip), about +0.2 s per answer; a question with an unseen term returns in
  ~0.7 s instead of a full answer. guidelines-mcp memory unchanged within noise (889 MiB).
- Known gaps: a new drug whose name is also an English word with a spaCy vector (fenoldopam) is not
  caught by check 2 (the generator's own abstention remains); check 3 knows only lexicon drugs.
  A question that misspells a drug ("metformine") now abstains and names the word, which is the
  intended behaviour for voice but is a false block for typed questions with typos.
- Check 3 caught nothing in the stored answers: its value is as a guard for prompts or models that
  behave like the v2 trial, not a measured gain on the current one.
