# ADR-0026: Quality gates in CI

Status: Proposed · Date: 2026-10-28

## Context

SPEC section 7 asks for CI that runs "schema lint, prompt render tests, then the golden-set
regression" and fails "if a quality metric drops below its threshold"; section 11 for a pull
request that fails "when faithfulness, citation precision or schema validity fall below
threshold, or when any PHI leak test fails". CI ran lint, type checks and the unit tests: the
retrieval regression on a committed fixture index (Phase 2 task 12), but not the red-team suite
(`just eval redteam`, only in `just gate 3`), not the de-ID recall gates (`just eval privacy`)
and nothing about prompts. A prompt could change without a new version, so the version written
into every trace and audit row would no longer name one text, and the answer quality reported
for `answer_cited@v1` would silently describe another prompt.

CI has no provider keys, by design (`.github/workflows/ci.yml`): the free tiers are rate limited
and a pull request from a fork must not spend them. So CI cannot re-run the answer evaluation.

## Options

1. Run the answer evaluation in CI with repository secrets: free-tier daily limits (one full run
   uses most of Groq's 200k tokens a day), keys exposed to pull-request workflows, minutes per run.
2. Replay cached model responses in CI: the cache is keyed by the prompt, so a prompt change
   misses it, which is the case the gate is for; and the cache holds model output for the
   golden set (no PHI, but large and outside git today).
3. **Gate on committed evidence.** Every prompt version is locked to its content; the answer
   evaluation stays local, its rows are committed, and CI checks that they were made with the
   prompts and model the repo now uses and meet floors. Everything that needs no model runs in
   CI as it is: the red-team suite with its control, and the de-ID gates.

## Decision

Option 3, as unit tests, so `just test-unit` and the `lint-unit` job (required on `main`) run
them; no workflow change.

- **Prompt contracts** (`tests/unit/test_prompts.py`): every file in `prompts/` and
  `prompts/experiments/` loads with the loader its code uses, has a task with a gateway alias, a
  quoted version and a valid reasoning effort, and its templates ask for exactly the fields its
  code fills in (a new `{field}` fails here, not as a KeyError in a request). A trial keeps the id
  of the prompt it would replace, under a version of its own.
- **Prompt lock** (`prompts/versions.lock`, `llmops/prompt_lock.py`, `just prompt-lock`): the
  SHA-256 of every prompt version's parsed content (text and call settings; comments and line
  endings do not count). A changed text under a locked version fails, so does an unlocked
  version; locking adds, never replaces. History checked first: no version in git history ever
  had two texts; `note_writer@v1` (retired) is locked from history so its number is not reused.
- **Answer evidence gate** (`config/quality_gates.yaml`, `evals/quality_gates.py`,
  `just quality-gates`): the chosen pipeline's committed rows
  (`evals/reports/rag/answers/hybrid_colbert_ctx.jsonl`, 60 questions) must carry the current
  `answer_cited` and `judge_citations` versions; the task's alias and the alias's deployment must
  be the ones evaluated (`clinscribe-fallback-groq`, `groq/openai/gpt-oss-20b`); every answer
  must be served by that alias; and the rows' summary must meet the floors: faithfulness ≥ 0.90
  (0.935), correctness ≥ 0.85 (0.910), citation precision ≥ 0.85 (0.871), correct abstentions
  ≥ 0.90 (1.0), false abstentions ≤ 0.10 (0.02), no judge or answer errors.
- **Red-team in CI**: all 67 cases pass; with the dose, diagnosis and injection rules and the
  subject checks off, all 38 cases of those categories fail (the suite can fail).
- **De-ID gates in CI** with the default recogniser (spaCy, what CI and a fresh clone run):
  structured recall 1.0, names ≥ 0.99, places ≥ 0.98, over-redaction ≤ 1%; a de-identifier that
  changes nothing fails them.

## Consequences

- A prompt change for the cited answer, or a move of its task to another model, fails CI until a
  new version is locked and its evaluation committed. That costs a local run per change
  (`just answers`: 60 answers take most of a day's free Groq budget for gpt-oss-20b, the judge
  runs on another model): deliberate.
- The floors are regression limits a little below the measured values, not the SPEC targets.
  Citation precision's floor (0.85) is below SPEC section 1's 0.95; the README states that gap.
- CI checks evidence, not behaviour: rows made with an edited copy of the code would pass. The
  rows record versions, and the review of the pull request that commits them is the control.
- Not gated: the note writer, the agentic loop's prompts (`grade_evidence`, `rewrite_query`) and
  the contextual prefixes have no committed rows that record their versions; they are locked and
  render-tested only. The PHI leak test needs the stack and real calls, so it stays in
  `just gate 1` (`just eval leak`); CI runs its no-stack part, the de-ID gates, and the span and
  log redaction unit tests it already had.
- `just test-unit` takes about 30 s longer (red-team twice, de-ID once).
