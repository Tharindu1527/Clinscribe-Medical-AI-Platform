# ADR-0025: Reasoning effort for the cited answer

Status: Proposed · Date: 2026-10-27

## Context

The cited answer (`prompts/answer_cited.yaml`, Groq gpt-oss-20b) is the largest stage of a voice
turn: Ask p50 2.1 s and p95 4.9 s of a time to first audio of 4.3 / 7.1 s against SPEC §1's 1.5 s
(`evals/reports/voice/latency.md`). gpt-oss reasons before it answers, and the prompt sets no
reasoning effort, so the provider's default applies. Over the last week the gateway's answer calls
averaged 337 completion tokens for an answer of about 100–150 tokens of JSON: most of the output
is reasoning. PROGRESS had the open question "decide the thinking level per task from the latency
and quality evals".

Also measured on the way (`tts_probe`, this machine): a TCP connect to Deepgram takes ~550 ms, a
new HTTPS request to Aura ~1.5 s to its first byte, a reused connection ~440 ms and the open
websocket the agent keeps (LiveKit prewarms it) ~770 ms. The latency report's TTS stage (1.4 s)
was the cold case, not what the agent does.

## Options

1. Keep the default effort.
2. **Set `reasoning_effort: low`** for the cited answer.
3. Stream the answer and speak the first sentence that passes the guardrails (a larger change:
   streaming through the gateway, per-sentence checks, no retry once a sentence was spoken).

## Decision rule (written before the results)

Option 2 is adopted only if, on the Phase 2 answer evaluation's 60 questions with the same
passages (`evals/rag/answer_eval.py`, chosen pipeline): correctness and faithfulness are not
worse by more than 0.05 (lower bound of the paired 95% bootstrap interval of the difference above
−0.05), correct abstentions do not fall, and the answer call's median latency, timed uncached on
the same passages, is lower.

## Measuring it (found before any result was read)

- **Setting an effort broke the last fallback.** LiteLLM's `drop_params` keeps `reasoning_effort`
  for Ollama, as its `think` option, and `llama3.2:3b` refuses it (400 "does not support
  thinking"). A Groq outage would have left every answer without its local fallback. The local
  and OpenRouter deployments now list it in `additional_drop_params`. Checked live: the local
  alias answers a request that sets the effort; a config test covers every fallback target.
- **A fallback timed the wrong model.** The first timing run hit Groq's daily limit (200,000
  tokens per rolling day for gpt-oss-20b on the free tier, stated in its 429). The gateway then
  answered the production prompt's calls with the local model (14-token abstentions after 6–38 s),
  while the trial's calls, which the local model refused, waited for Groq. Evaluations now send
  `disable_fallbacks`. Checked live with the budget spent: 429 with it, a llama3.2 answer without
  it. The 60 stored baseline answers and the trial's answers were all served by Groq (the cache
  keeps the served model).
- **The gateway's own retries landed in the latency.** With `num_retries: 1`, LiteLLM waits out a
  per-minute limit inside the request, so 1 s answers were timed at up to 60 s. The client now
  records `x-litellm-attempted-retries`; the timing script spaces calls 20 s apart, measures a
  retried answer again, and runs after the quality trial so the two do not share a minute's
  budget.

## Result

`prompts/experiments/answer_cited_low.yaml` (the production prompt with `reasoning_effort: low`),
60 of 60 questions, every answer of both prompts served by Groq gpt-oss-20b, judged by
`judge_citations` (`just answers`, rows `hybrid_colbert_ctx_low`):

| | default effort | low | difference, 95% paired bootstrap | rule |
|---|---|---|---|---|
| correctness (n 50) | 0.910 | 0.890 | −0.020 [−0.080, +0.030] | lower bound below −0.05: **fails** |
| faithfulness (n 46 both answered) | 0.931 | 0.942 | +0.011 [−0.062, +0.076] | lower bound below −0.05: **fails** |
| citation precision (n 46) | 0.862 | 0.895 | +0.033 [−0.045, +0.106] | not in the rule |
| correct abstentions | 10/10 | 9/10 | | fell: **fails** |
| false abstentions (answerable) | 1/50 | 4/50 | | not in the rule |
| output tokens per answer, median | 282 | 98 | | |

The latency criterion was not needed: the quality criteria failed first. A paired uncached timing
of both prompts (`evals/rag/answer_latency.py`, 10 questions) records what was at stake; it runs
on what is left of Groq's daily token budget after the trial and is added here when it completes.
The latencies stored with the trial are not used: 19 of its 60 answers include a rate-limit wait
inside the gateway, and the production rows (2026-10-09) did not record one.

The abstention it missed is the wrong-drug case of ADR-0017 and ADR-0018 again: "Which
gastrointestinal side effects does mazdutide cause?" (mazdutide is not in the corpus) answered
from the semaglutide label, faithfulness 0.25. In the full system ADR-0018's question-subject
check abstains on that question before any model runs, but the rule was written for the
generator alone and is applied as written. The three new false abstentions are questions the
default effort answered with correctness 1.0 (apixaban in severe liver impairment), 0.5 (how
often childhood pneumonia leads to an effusion or empyema) and 0.0 (WHO's first-line choice by
age and ancestry).

## Decision

**Not adopted.** The cited answer keeps the provider's default reasoning effort. Low effort
cut the output by two thirds, but the intervals for correctness and faithfulness do not rule out
a loss larger than the margin, and it answered a question it should have abstained on.

## Consequences

- `prompts/answer_cited.yaml` is unchanged; the trial prompt stays in `prompts/experiments/` for
  a re-run with another model.
- Kept from building the trial: the effort is a prompt setting (`reasoning_effort`, none by
  default), the last fallbacks drop it instead of failing, evaluations can turn fallbacks off
  (`GatewayClient.complete(fallbacks=False)`), and the client records the gateway's own retries
  (`Completion.retries`), which also showed that latencies stored by earlier evaluations can
  include rate-limit waits.
- The voice budget is still not met. The cheap lever did not hold quality, so the next option
  is the larger one: streaming the answer and speaking the first checked sentence (option 3).
