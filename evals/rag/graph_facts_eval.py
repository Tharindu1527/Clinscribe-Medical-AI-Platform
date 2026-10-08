"""Graph-only check (Phase 2 task 10): can DDInter facts answer what the text corpus does not name?

Pairs: Major DDInter interactions between two in-scope corpus drugs that no chunk names together
(10 on 2026-10-08). Question: "Is there a known drug interaction between A and B?". Both arms use
the best pipeline's top 5 chunks (hybrid + ColBERT + context); the graph arm adds the DDInter fact
as one more citable source. Same generator and judge as answer_eval. Illustrative only: 10 pairs.

Usage: uv run python -m evals.rag.graph_facts_eval   (needs `just up rag` and the gateway)
"""

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from evals.golden.candidates import AREA_DRUGS
from evals.golden.golden import GoldenItem
from evals.rag.answer_eval import (
    CACHE,
    JUDGE_FILE,
    OUT,
    REPORTS,
    BudgetExhaustedError,
    PatientClient,
    judge_messages,
    metrics,
    parse_judgment,
)
from evals.rag.retrieval_eval import SYSTEMS
from llmops.gateway.client import GatewayClient, ReplayCache, alias_for
from privacy.deid.types import issue
from retrieval.generate import AnswerGenerator, load_spec, source_block
from retrieval.graph.lexicon import DrugLexicon
from retrieval.graph.load import GRAPH_DIR, Neo4jHTTP, read_jsonl
from retrieval.graph.rag import GraphRetriever, fact_sources

ROOT = Path(__file__).resolve().parents[2]
TOP_K = 5


def graph_only_pairs(client: Neo4jHTTP, lexicon: DrugLexicon) -> list[tuple[str, str]]:
    keys = sorted({k for drugs in AREA_DRUGS.values() for d in drugs for k in lexicon.find(d)})
    rows = client.run(
        "MATCH (a:Drug)-[:INTERACTS_WITH {level: 'Major'}]-(b:Drug) "
        "WHERE a.key IN $k AND b.key IN $k AND a.key < b.key "
        "AND NOT EXISTS { MATCH (a)<-[:MENTIONS]-(:Chunk)-[:MENTIONS]->(b) } "
        "RETURN a.name AS a, b.name AS b ORDER BY a, b",
        k=keys,
    )
    return [(r["a"], r["b"]) for r in rows]


def items_for(pairs: Sequence[tuple[str, str]]) -> list[GoldenItem]:
    return [
        GoldenItem(
            id=f"g9{n:03d}",
            question=f"Is there a known drug interaction between {a.lower()} and {b.lower()}?",
            answerable=True,
            answer=f"{a} and {b}: Major interaction",
            gold_chunk_ids=[f"graph:ddinter:{a}|{b}"],
            area="anticoagulation",  # placeholder: the schema needs an area; not used here
            qtype="interaction",
            source="openfda",  # placeholder: the answer comes from DDInter, not a corpus source
            drafted_by="graph_facts_eval",
        )
        for n, (a, b) in enumerate(pairs, start=1)
    ]


def main() -> int:
    from config.settings import Settings

    settings = Settings()
    neo4j = Neo4jHTTP()
    lexicon = DrugLexicon(read_jsonl(GRAPH_DIR / "drugs.jsonl"))
    graph = GraphRetriever(neo4j, lexicon)
    pairs = graph_only_pairs(neo4j, lexicon)
    retriever, _ = SYSTEMS["hybrid_colbert_ctx"]()
    corpus = {c["id"]: c for c in read_jsonl(ROOT / "data" / "corpus" / "chunks.jsonl")}
    gateway = GatewayClient(
        settings.gateway_url,
        settings.litellm_app_key,
        cache=ReplayCache(CACHE, "record"),
        timeout=180.0,
    )
    client = PatientClient(gateway)
    spec = load_spec()
    judge_spec = yaml.safe_load(JUDGE_FILE.read_text(encoding="utf-8"))
    generator = AnswerGenerator(client, alias_for(spec.task), spec)
    rows: list[dict[str, Any]] = []
    try:
        for item in items_for(pairs):
            query = issue(item.question, "synthetic-graph-question")
            chunks = [corpus[h.chunk_id] for h in retriever.search(query, k=TOP_K)]
            facts = graph.facts(query)
            for arm, sources in (("text", chunks), ("text+graph", [*chunks, *fact_sources(facts)])):
                answer = generator.answer(query, sources)
                judgment = None
                if not answer.abstained:
                    _, labels = source_block(sources)
                    reply = client.complete(
                        alias_for(judge_spec["task"]),
                        judge_messages(judge_spec, item, sources, answer),
                        temperature=0.0,
                        max_tokens=judge_spec["max_tokens"],
                        response_format={"type": "json_object"},
                    )
                    try:
                        judgment = parse_judgment(reply.text, answer, labels)
                    except (ValueError, json.JSONDecodeError):
                        judgment = None
                cites_graph = any(
                    c.startswith("graph:") for s in answer.sentences for c in s.chunk_ids
                )
                rows.append(
                    {
                        "pair": item.question,
                        "arm": arm,
                        "facts": facts,
                        "answer": answer.model_dump(),
                        "judgment": judgment,
                        "cites_graph": cites_graph,
                        "metrics": metrics(item, answer, judgment),
                    }
                )
                print(f"{arm:10} {item.question[44:]:55} {rows[-1]['metrics']}", file=sys.stderr)
    except BudgetExhaustedError as exc:
        print(f"stopped: {exc}; rerun later (answers are cached)")
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "graph_facts.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    lines = [
        "# Graph-only questions: text vs text + DDInter facts",
        "",
        f"{len(pairs)} Major DDInter pairs between corpus drugs that no chunk names together. "
        "Illustrative (small n); same generator and judge as the answer evaluation.",
        "",
        "| arm | answered | states the interaction | cites the graph | faithfulness |",
        "|---|---|---|---|---|",
    ]
    for arm in ("text", "text+graph"):
        arm_rows = [r for r in rows if r["arm"] == arm]
        answered = [r for r in arm_rows if not r["metrics"]["abstained"]]
        correct = sum(r["metrics"].get("correctness", 0.0) for r in arm_rows) / len(arm_rows)
        faithful = [
            r["metrics"]["faithfulness"] for r in answered if "faithfulness" in r["metrics"]
        ]
        lines.append(
            f"| {arm} | {len(answered)}/{len(arm_rows)} | {correct:.2f} | "
            f"{sum(r['cites_graph'] for r in arm_rows)} | "
            f"{sum(faithful) / len(faithful) if faithful else float('nan'):.2f} |"
        )
    path = REPORTS / "answers_graph_facts.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
