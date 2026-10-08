"""PROGRESS Phase 2 task 9 gate: the drug graph is loaded with the expected counts and known pairs.

Needs `just up rag` and `just graph`; skipped otherwise unless CLINSCRIBE_REQUIRE_RAG=1.
"""

import os

import pytest

from privacy.deid.types import issue
from retrieval.graph.lexicon import DrugLexicon
from retrieval.graph.load import GRAPH_DIR, Neo4jHTTP, counts, read_jsonl
from retrieval.graph.rag import GraphRetriever


@pytest.fixture(scope="module")
def client() -> Neo4jHTTP:
    try:
        client = Neo4jHTTP()
        loaded = bool(client.run("MATCH (m:Meta {name: 'drug_graph'}) RETURN m.name AS n"))
    except Exception:  # noqa: BLE001 - Neo4j down or unreachable
        loaded = False
    if not loaded:
        if os.environ.get("CLINSCRIBE_REQUIRE_RAG") == "1":
            pytest.fail("drug graph not loaded (just up rag; just graph)")
        pytest.skip("drug graph not loaded (just up rag; just graph)")
    return client


def test_graph_counts_match_the_sources(client: Neo4jHTTP) -> None:
    found = counts(client)
    assert found["drugs"] == len(read_jsonl(GRAPH_DIR / "drugs.jsonl"))
    assert found["interactions"] == len(read_jsonl(GRAPH_DIR / "interactions.jsonl"))
    assert set(found["interactions_by_level"]) <= {"Major", "Moderate", "Minor", "Unknown"}
    assert found["chunks"] >= 8000
    assert found["chunks_with_mentions"] > 0.3 * found["chunks"]


@pytest.mark.parametrize(
    ("a", "b"),
    [("Warfarin", "Clarithromycin"), ("Simvastatin", "Clarithromycin"),
     ("Spironolactone", "Lisinopril")],
)  # fmt: skip
def test_known_major_interactions_are_present(client: Neo4jHTTP, a: str, b: str) -> None:
    rows = client.run(
        "MATCH (x:Drug {name: $a})-[r:INTERACTS_WITH]-(y:Drug {name: $b}) RETURN r.level AS level",
        a=a,
        b=b,
    )
    assert [r["level"] for r in rows] == ["Major"]


def test_graph_candidates_mention_both_drugs(client: Neo4jHTTP) -> None:
    graph = GraphRetriever(client, DrugLexicon(read_jsonl(GRAPH_DIR / "drugs.jsonl")))
    query = issue(
        "Is it safe to give clarithromycin to a patient on warfarin?", "synthetic-test-fixture"
    )
    hits = graph.search(query, k=10)
    assert hits
    chunks = {
        c["id"]: c["text"].lower() for c in read_jsonl(GRAPH_DIR.parent / "corpus" / "chunks.jsonl")
    }
    top = chunks[hits[0].chunk_id]
    assert "warfarin" in top
    assert "clarithromycin" in top
    assert {f["level"] for f in graph.facts(query)} == {"Major"}
