# ADR-0030: A thinking budget for gemini-2.5-flash in the default pool

Status: Proposed (adopted after the test below passed) · Date: 2026-10-29

## Context

The note writer (`prompts/note_writer.yaml` v2, task `note_writer`) asks the default pool
(`clinscribe-default`: four Gemini Flash models, ADR-0001) for at most 4,500 output tokens: the most
Groq's free per-minute limit leaves when the request falls back. Gemini's thinking tokens count
against that limit. Re-recording the demo video, two drafts of one consultation ended "no draft
produced" (PROGRESS, 2026-10-29): the reply was cut off on gemini-2.5-flash, then the retry too.

The gateway's spend log (no model calls) shows it is that model. Note-sized calls (1,500+ output
tokens) of the default pool, 2026-10-05 to 2026-10-28:

| model | note-sized calls | at the 4,500 limit | median thinking tokens |
|---|---|---|---|
| gemini-2.5-flash | 17 | **8** | 3,169 |
| gemini-3.5-flash | 5 | 1 | 1,716 |
| gemini-3.6-flash | 7 | 0 | 1,288 |
| gemini-3.5-flash-lite | 0 | 0 | - |

The note itself (output minus thinking) took 950-2,000 tokens in the replies that were not cut off;
one cut-off reply spent 4,316 of 4,495 tokens thinking. The same model's short calls (evidence
grading, query rewrites; under 1,500 output tokens) think a median of 128 tokens, and 3 of 98 more
than 1,024.

## Options

1. **A thinking budget on the gemini-2.5-flash deployment** (`thinking: {type: enabled,
   budget_tokens: 1024}`; LiteLLM sends Gemini 2.5 `thinkingBudget`). Touches only the model that
   overruns; its short tasks almost never think that long.
2. A lower reasoning effort in the note writer prompt: every model in the pool and the Groq
   fallback, including the three that rarely or never overrun.
3. A note-writer alias without gemini-2.5-flash: a fifth of the pool's free daily quota lost to
   the task that needs it most.
4. A larger output limit: bound by the Groq fallback's per-minute limit (Phase 3 task 6).

## Decision

Option 1, if it passes a rule written before any draft was made with the budget.

The test pins the note writer to that deployment with the budget: a new alias
`clinscribe-eval-gemini-2.5-flash` (an evaluation alias, never a fallback target) and no fallbacks,
on the 8 ACI-Bench dialogues of the note-quality evaluation (`evals/agents/note_quality.py
--alias clinscribe-eval-gemini-2.5-flash`), with the same judge. Adopt it on the pool deployment
only if all three hold:

1. **complete:** every dialogue gets a draft and no note-writer reply stops at the output limit
   (finish reason "length");
2. **as good:** fact recall at least 0.80 and critical-fact recall at least 0.87, against 0.85 and
   0.92 for the committed run on the pool (`evals/reports/agents/note_quality.md`; margin 0.05);
3. **supported:** at most 3% of statements unsupported by the turns they cite (committed run: 3 of
   171).

**Result (2026-10-29): all three hold; adopted.** The budget is now on the pool's gemini-2.5-flash
deployment (`llmops/gateway/config.yaml`); the evaluation alias stays for later pinned tests.
Report: `evals/reports/agents/note_quality_clinscribe-eval-gemini-2.5-flash.md` (the run took 14
resumptions over the model's 20 free requests a day).

| | pool, committed | pinned, with the budget | rule |
|---|---|---|---|
| drafts | 8 of 8 | 8 of 8 | every dialogue |
| note-writer replies cut off | - (not recorded then) | **0 of 8** | 0 |
| fact recall | 0.85 | **0.90** | ≥ 0.80 |
| critical-fact recall | 0.92 | **0.92** | ≥ 0.87 |
| statements unsupported | 3 of 171 (1.8%) | **6 of 280 (2.1%)** | ≤ 3% |

No draft needed a second attempt. Thinking took a median of 910 and at most 1,022 tokens, so the
cap held on every call; the notes themselves took 970-1,960 tokens, inside the 3,476 the cap
leaves. The drafts are longer
(35 statements against 21), which also lifts the "without assessment and plan" control (0.72 / 0.69
against 0.60 / 0.50): more of the reference's facts are in the subjective and objective sections.
Latency per reply p50 16.2 s; the slowest, 77.2 s, includes one gateway retry (a rate-limit wait
inside the request); without it the slowest is 24.9 s.

Found while reading the results, not part of the rule: the harness dropped ACI-Bench lines without a
speaker tag, and D2N072's whole assessment and plan is on such a line, so its 0.60 / 0.59 here (and
0.72 / 0.65 on the pool) measure a transcript without the plan. The decision above stands on the
harness the rule was written for; the fixed harness's numbers are in the update below.

**Update (2026-10-29): the harness fixed.** An untagged line now continues the turn above it
(`evals/agents/note_eval.py turns()`; only D2N072 and D2N068 change, D2N068 is not in the sample).
D2N072 re-drafted, both runs, the other seven replayed from the cache:

| D2N072 | before (no plan in the transcript) | after |
|---|---|---|
| pinned, with the budget | recall 0.60, critical 0.59 | **0.88, 1.00** (2 replies: one guardrail retry, neither cut off; 3 statements unsupported) |
| pool | 0.72, 0.65 | **1.00, 1.00** (0 unsupported) |

Means over the 8 on the fixed harness: pinned fact recall 0.94, critical 0.97, 8 of 288 statements
unsupported (2.8%); pool 0.89, 0.96, 3 of 172. The pinned run passes the rule there as well, with
less room on support (2.8% against the 3% limit). The pool report's seven cached drafts came from
whichever model answered before the budget; its D2N072 draft is the only one made with it in place.

## Consequences

- The comparison is not paired by model: the committed run's drafts came from whichever pool model
  answered. Eight dialogues and one judge, no clinician: indicative, as in the note-quality report.
- The budget also applies to that model's short tasks; the spend log suggests it rarely binds there
  (3 of 98 calls), and their quality on it is not measured separately.
- `GatewayClient` now records the finish reason and thinking tokens of every call
  (`Completion.finish_reason`, `Completion.reasoning_tokens`), so a cut-off is visible as such.
