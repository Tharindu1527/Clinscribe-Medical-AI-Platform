"""Cost per consultation by model choice (Phase 6; SPEC section 11).

A consultation = one Scribe draft + three Ask questions (Lab mode makes no model calls). Token
counts are measured: the note writer on an ACI-Bench dialogue (2,136 in / 2,359 out incl. 1,732
reasoning tokens, Groq gpt-oss-20b) and 1.4 calls per draft (3 of 8 drafts needed the retry);
Ask answers 1,466 in / 268 out (mean of 290 gateway spend-log rows); 17% of questions take the
agentic path (39/235 golden questions, router report) and add one grading call
(~1,500 in / 150 out).
Prices: LiteLLM's model cost map (list prices, USD per token) read from the running gateway on
2026-10-14. Every model is costed on the same token counts, so models that reason more than
gpt-oss-20b are under-estimated. The free tiers used in this build bill $0.

  uv run python -m evals.llmops.cost_report
"""

import sys
from pathlib import Path

REPORT = (
    Path(__file__).resolve().parents[2]
    / "evals"
    / "reports"
    / "llmops"
    / "cost_per_consultation.md"
)

DRAFT = (1.4 * 2136, 1.4 * 2359)
ASK = (3 * 1466, 3 * 268)
AGENTIC = (3 * 0.17 * 1500, 3 * 0.17 * 150)
PRICES = {  # (input, output) USD per token
    "gemini/gemini-3.5-flash": (1.5e-06, 9e-06),
    "gemini/gemini-3.6-flash": (7.5e-07, 3.75e-06),
    "gemini/gemini-2.5-flash": (3e-07, 2.5e-06),
    "gemini/gemini-3.5-flash-lite": (3e-07, 2.5e-06),
    "groq/openai/gpt-oss-120b": (1.5e-07, 6e-07),
    "groq/openai/gpt-oss-20b": (7.5e-08, 3e-07),
    "ollama_chat/llama3.2:3b (local)": (0.0, 0.0),
}


def main() -> int:
    tokens_in = DRAFT[0] + ASK[0] + AGENTIC[0]
    tokens_out = DRAFT[1] + ASK[1] + AGENTIC[1]
    lines = [
        "# Cost per consultation, by model choice",
        "",
        f"One consultation = 1 Scribe draft + 3 Ask questions: ~{tokens_in:,.0f} input and "
        f"~{tokens_out:,.0f} output tokens (method in `evals/llmops/cost_report.py`). List prices;",
        "the free tiers used in this build bill $0.",
        "",
        "| model | draft USD | 3 questions USD | consultation USD | per 1,000 consultations |",
        "|---|---|---|---|---|",
    ]
    for model, (p_in, p_out) in PRICES.items():
        draft = DRAFT[0] * p_in + DRAFT[1] * p_out
        ask = (ASK[0] + AGENTIC[0]) * p_in + (ASK[1] + AGENTIC[1]) * p_out
        lines.append(
            f"| {model} | {draft:.4f} | {ask:.4f} | {draft + ask:.4f} | "
            f"{1000 * (draft + ask):,.2f} |"
        )
    lines += [
        "",
        "The local model costs no API fee but is slow on the 4 GB laptop GPU (23-44 s per",
        "question during the outage drill) and too small for long notes: a last resort.",
        "Output tokens dominate (reasoning counts as output), so the thinking level per task",
        "is the main cost lever after the model itself.",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(REPORT.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
