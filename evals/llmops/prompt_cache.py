"""Gemini implicit prompt caching (SPEC section 7: "the saving is measured using Gemini's implicit
caching"), from the gateway's spend log (LiteLLM_SpendLogs, prompt_tokens_details.cached_tokens).

1. Real traffic: every successful Gemini call the project has made, how many had a prompt long
   enough to be cached (Gemini needs a shared prefix of about 1,024 tokens on Flash) and how many
   tokens were served from the cache.
2. A controlled check: N calls through the usual alias (`clinscribe-default`, four Gemini models)
   that share one ~2,500-token prefix (public guideline text) and differ only in a short question
   at the end. A second call to the same model within minutes should report cached tokens.

  uv run python -m evals.llmops.prompt_cache [--n 12]   (needs `just up`; N free-tier calls)
  uv run python -m evals.llmops.prompt_cache --since "2026-10-25 14:13:32"   (report only)
Writes evals/reports/llmops/prompt_cache.md. Responses are not cached locally (each call is new).
"""

import argparse
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

from config.settings import Settings
from llmops.gateway.client import ChatMessage, GatewayClient
from privacy.deid.types import issue
from retrieval.dense import load_chunks

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "evals" / "reports" / "llmops" / "prompt_cache.md"
ALIAS = "clinscribe-default"
PREFIX_CHARS = 10_000  # ~2,500 tokens: above the minimum Gemini caches
LONG = 1024
TOTALS = """select model,
  count(*),
  count(*) filter (where prompt_tokens >= {long}),
  count(*) filter (where {cached} > 0),
  coalesce(sum(prompt_tokens), 0),
  coalesce(sum({cached}), 0)
from "LiteLLM_SpendLogs"
where model like 'gemini%' and status = 'success' {where}
group by model order by model;"""
CACHED = "coalesce((metadata->'usage_object'->'prompt_tokens_details'->>'cached_tokens')::int, 0)"


def spend_rows(sql: str) -> list[list[str]]:
    settings = Settings()
    out = subprocess.run(
        ["docker", "compose", "exec", "-T", "-e", "PGPASSWORD", "postgres", "psql", "-h",
         "localhost", "-U", "litellm", "-d", "litellm", "-At", "-F", "|"],
        input=sql,
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PGPASSWORD": settings.litellm_db_password.get_secret_value()},
    )  # fmt: skip
    return [line.split("|") for line in out.stdout.splitlines() if line]


def prefix() -> str:
    """Public guideline text (the WHO hypertension guideline's first chunks), ~2,500 tokens."""
    chunks = [c for c in load_chunks()[0] if c["source"] == "who" and c["topic"] == "hypertension"]
    text = ""
    for chunk in chunks:
        if len(text) > PREFIX_CHARS:
            break
        text += f"\n\n{chunk['section']}\n{chunk['text']}"
    return (
        "You answer short questions about the guideline excerpt below, in one sentence each.\n"
        + text
    )


def check_rows(since: str) -> list[list[str]]:
    """The check's calls: Gemini rows with the shared prefix, in the 15 minutes from `since`."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", since):
        raise SystemExit("--since must look like 2026-10-25 14:13:32")
    return spend_rows(
        f"""select model, prompt_tokens, {CACHED}, "startTime" from "LiteLLM_SpendLogs"
        where model like 'gemini%' and prompt_tokens >= {LONG} and "startTime" >= '{since}'
          and "startTime" < timestamp '{since}' + interval '15 minutes'
        order by "startTime";"""  # noqa: S608 (validated timestamp, constants)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=12)
    parser.add_argument("--since", help="rebuild the report from an earlier check (UTC), no calls")
    args = parser.parse_args(argv)
    started = args.since or time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() - 60))
    before = f"and \"startTime\" < '{started}'"
    history = spend_rows(TOTALS.format(long=LONG, cached=CACHED, where=before))
    reported: list[int] = []  # cached tokens in each response
    if not args.since:
        settings = Settings()
        # traced: LiteLLM writes no spend-log row for a no-log call, and the row names the model
        gateway = GatewayClient(settings.gateway_url, settings.litellm_app_key)
        system = ChatMessage("system", issue(prefix(), "public-corpus"))
        for k in range(1, args.n + 1):
            question = f"Question {k}: in one sentence, what does part {k} of the excerpt cover?"
            reply = gateway.complete(
                ALIAS, [system, ChatMessage("user", issue(question, "synthetic"))], max_tokens=400
            )
            reported.append(reply.cached_input_tokens)
            print(f"call {k}: {reply.cached_input_tokens} cached", file=sys.stderr)
            time.sleep(2)
        for _ in range(24):  # LiteLLM writes spend logs in batches, minutes later
            if len(check_rows(started)) >= args.n:
                break
            time.sleep(15)
    calls = check_rows(started)
    lines = render(history, calls, len(calls), started)
    if reported:
        lines.append(f"Cached tokens as reported in each response: {reported}.")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


def render(history: list[list[str]], calls: list[list[str]], n: int, started: str) -> list[str]:
    lines = [
        "# Gemini implicit prompt caching (SPEC section 7)",
        "",
        "Generated by `evals/llmops/prompt_cache.py` from the gateway's spend log",
        "(`prompt_tokens_details.cached_tokens`). On the free tier cached tokens cost nothing",
        "either way; at list price Gemini bills cached input at a fraction of the normal rate.",
        "",
        "## 1. All successful Gemini calls so far",
        "",
        f"| Model | Calls | Prompt ≥ {LONG} tokens | Calls with cached tokens | Prompt tokens | "
        "Cached tokens |",
        "|---|---|---|---|---|---|",
    ]
    lines += [f"| {' | '.join(row)} |" for row in history]
    by_model: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for model, prompt, cached, _ in calls:
        by_model[model].append((int(prompt), int(cached)))
    lines += [
        "",
        f"## 2. Controlled check ({n} calls from {started} UTC, one shared ~2,500-token prefix)",
        "",
        "| Model | Calls | Prompt tokens per call | Cached tokens per call (in order) |",
        "|---|---|---|---|",
    ]
    for model, rows in sorted(by_model.items()):
        lines.append(
            f"| {model} | {len(rows)} | {', '.join(str(p) for p, _ in rows)} | "
            f"{', '.join(str(c) for _, c in rows)} |"
        )
    hits = sum(c > 0 for rows in by_model.values() for _, c in rows)
    repeats = sum(max(0, len(rows) - 1) for rows in by_model.values())
    cached_total = sum(c for rows in by_model.values() for _, c in rows)
    prompt_total = sum(p for rows in by_model.values() for p, _ in rows)
    lines += [
        "",
        f"Calls served partly from the cache: {hits} of {len(calls)} ({repeats} were repeats to a "
        f"model already called); cached share of all prompt tokens: "
        f"{cached_total / prompt_total:.0%}."
        if prompt_total
        else "No spend-log rows found for the calls.",
    ]
    return lines


if __name__ == "__main__":
    sys.exit(main())
