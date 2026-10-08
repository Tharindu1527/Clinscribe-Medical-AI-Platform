"""Cross-check the task 10 judge against RAGAS faithfulness on a sample of answered questions.

RAGAS splits each answer into claims and checks each claim against the retrieved contexts. It runs
through the gateway (ADR-0001) on the Gemini pool (`clinscribe-default`), a different model family
from our judge (`clinscribe-judge`, gpt-oss-120b): agreement means more than one model agreeing
with itself. RAGAS and LangChain are not project dependencies; run in a throwaway env
(langchain < 1, because ragas 0.4.3 imports a module that langchain-community 0.4 removed):

  uv run --with "ragas==0.4.3" --with "langchain-community<0.4" --with "langchain-openai<1" \
         --with "langchain<1" --with "langchain-core<1" python -m evals.rag.ragas_check
"""

import importlib
import json
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
ANSWERS = ROOT / "evals" / "reports" / "rag" / "answers"
SYSTEMS = ("dense", "hybrid_colbert_ctx")
PER_SYSTEM = 10
SEED = 5
ALIAS = "clinscribe-default"


def spearman(a: list[float], b: list[float]) -> float:
    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            for k in range(i, j + 1):
                out[order[k]] = (i + j) / 2  # average rank for ties
            i = j + 1
        return out

    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True))
    var = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return cov / var if var else float("nan")


def main() -> int:
    from config.settings import Settings
    from evals.golden.golden import load_items

    ragas: Any = importlib.import_module("ragas")
    metrics_mod: Any = importlib.import_module("ragas.metrics")
    llms: Any = importlib.import_module("ragas.llms")
    lc_openai: Any = importlib.import_module("langchain_openai")
    settings = Settings()
    questions = {i.id: i.question for i in load_items()}
    corpus = {
        (c := json.loads(line))["id"]: c["text"]
        for line in (ROOT / "data" / "corpus" / "chunks.jsonl").read_text("utf-8").splitlines()
    }
    rng = random.Random(SEED)
    picked: list[tuple[str, dict[str, Any]]] = []
    for system in SYSTEMS:
        rows = [
            json.loads(x) for x in (ANSWERS / f"{system}.jsonl").read_text("utf-8").splitlines()
        ]
        rows = [r for r in {r["id"]: r for r in rows}.values() if "faithfulness" in r["metrics"]]
        picked += [(system, r) for r in rng.sample(sorted(rows, key=lambda r: r["id"]), PER_SYSTEM)]
    samples = [
        ragas.SingleTurnSample(
            user_input=questions[r["id"]],
            response=" ".join(s["text"] for s in r["answer"]["sentences"]),
            retrieved_contexts=[corpus[c] for c in r["chunk_ids"]],
        )
        for _, r in picked
    ]
    llm = llms.LangchainLLMWrapper(
        lc_openai.ChatOpenAI(
            model=ALIAS,
            base_url=settings.gateway_url.rstrip("/") + "/v1",
            api_key=settings.litellm_app_key.get_secret_value(),
            temperature=0.0,
            max_retries=6,
            timeout=180,
        )
    )
    result = ragas.evaluate(
        ragas.EvaluationDataset(samples=samples), metrics=[metrics_mod.Faithfulness()], llm=llm
    )
    scores = [float(s) for s in result.to_pandas()["faithfulness"]]
    ours = [float(r["metrics"]["faithfulness"]) for _, r in picked]
    pairs = [(a, b) for a, b in zip(scores, ours, strict=True) if a == a]  # drop NaN (RAGAS failed)
    agree = sum((a == 1.0) == (b == 1.0) for a, b in pairs)
    lines = [
        "# Judge cross-check: our judge vs RAGAS faithfulness",
        "",
        f"{len(picked)} answered questions ({PER_SYSTEM} per system: {', '.join(SYSTEMS)}). "
        f"RAGAS 0.4.3 faithfulness through the gateway alias `{ALIAS}` (Gemini pool); our judge is "
        "`clinscribe-judge` (gpt-oss-120b, prompts/judge_citations.yaml).",
        "",
        f"- scored by RAGAS: {len(pairs)} of {len(picked)}",
        f"- mean faithfulness: RAGAS {sum(a for a, _ in pairs) / len(pairs):.3f}, "
        f"ours {sum(b for _, b in pairs) / len(pairs):.3f}",
        f"- Spearman correlation: {spearman([a for a, _ in pairs], [b for _, b in pairs]):.2f}",
        f"- agreement on 'fully faithful' (score 1.0): {agree} of {len(pairs)}",
        "",
        "| id | system | RAGAS | ours |",
        "|---|---|---|---|",
        *[
            f"| {r['id']} | {system} | {a:.2f} | {r['metrics']['faithfulness']:.2f} |"
            for (system, r), a in zip(picked, scores, strict=True)
        ],
    ]
    path = ROOT / "evals" / "reports" / "rag" / "ragas_calibration.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
