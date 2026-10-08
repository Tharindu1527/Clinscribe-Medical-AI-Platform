"""Drug lexicon, interaction router, mention filtering and GraphRAG plumbing (no Neo4j needed)."""

from typing import Any

import pytest

from privacy.deid.types import DeidentifiedText, issue
from retrieval.dense import Hit
from retrieval.graph.lexicon import DrugLexicon, salt_free
from retrieval.graph.load import mentions
from retrieval.graph.rag import GraphAugmentedPool, GraphRetriever, route
from retrieval.graph.sources import parse_ddinter

DRUGS: list[dict[str, Any]] = [
    {"ddinter_id": "D1", "name": "Warfarin", "ingredient": "warfarin", "brands": ["Coumadin"]},
    {"ddinter_id": "D2", "name": "Clarithromycin", "ingredient": "clarithromycin", "brands": []},
    {"ddinter_id": "D3", "name": "Lithium carbonate", "ingredient": "lithium carbonate",
     "brands": ["Lithobid"]},
    {"ddinter_id": "D4", "name": "Insulin glargine", "ingredient": "insulin glargine",
     "brands": ["Lantus"]},
    {"ddinter_id": "D5", "name": "Potassium chloride", "ingredient": None, "brands": ["Focus"]},
    {"ddinter_id": "D6", "name": "Insulin", "ingredient": None, "brands": []},
]  # fmt: skip
LEX = DrugLexicon(DRUGS)


def test_generic_names_match_case_insensitively_and_brands_only_capitalised() -> None:
    assert LEX.find("WARFARIN with clarithromycin") == {"D1", "D2"}
    assert LEX.find("She takes Coumadin daily.") == {"D1"}
    assert LEX.find("the focus of treatment") == set()  # lower-case brand word: not a drug
    assert LEX.find("Focus 20 mEq") == {"D5"}


def test_salt_free_alias_but_not_for_electrolytes() -> None:
    assert salt_free("Lithium carbonate") == "lithium"
    assert salt_free("Potassium chloride") is None  # "potassium" usually means the lab value
    assert salt_free("Warfarin") is None
    assert LEX.find("Lithium levels rose") == {"D3"}
    assert LEX.find("check potassium daily") == set()


def test_longest_match_wins() -> None:
    assert LEX.find("insulin glargine at night") == {"D4"}  # not also plain "insulin"
    assert LEX.find("insulin at night") == {"D6"}


def test_router_needs_two_drugs_or_one_drug_and_an_interaction_cue() -> None:
    assert route("Is warfarin safe with clarithromycin?", LEX) == ["D1", "D2"]
    assert route("Which drugs interact with warfarin?", LEX) == ["D1"]
    assert route("Does Coumadin raise the INR levels when taken together with food?", LEX) == ["D1"]
    assert route("What is the usual warfarin dose?", LEX) == []  # one drug, no cue
    assert route("Which antibiotics interact with each other?", LEX) == []  # no drug named


def test_everyday_substance_words_are_not_drugs_and_common_drugs_stay() -> None:
    lex = DrugLexicon([*DRUGS, {"ddinter_id": "D7", "name": "Dextrose", "ingredient": "glucose",
                                "brands": []}])  # fmt: skip
    assert lex.find("fasting glucose was high on warfarin") == {"D1"}
    chunks = [{"id": f"c{i}", "text": "warfarin and glucose"} for i in range(30)]
    assert mentions(lex, chunks)[:2] == [("c0", "D1"), ("c1", "D1")]  # warfarin kept everywhere
    assert len(mentions(lex, chunks)) == 30


def test_ddinter_pairs_are_undirected_and_keep_the_most_severe_level(tmp_path: Any) -> None:
    header = "DDInterID_A,Drug_A,DDInterID_B,Drug_B,Level\n"
    for group in ("A", "B", "C", "D", "G", "H", "J", "L", "M", "N", "P", "R", "S", "V"):
        (tmp_path / f"code_{group}.csv").write_text(header, encoding="utf-8")
    (tmp_path / "code_B.csv").write_text(
        header + "D2,Clarithromycin,D1,Warfarin,Moderate\nD1,Warfarin,D3,Lithium,Odd\n",
        encoding="utf-8",
    )
    (tmp_path / "code_J.csv").write_text(header + "D1,Warfarin,D2,Clarithromycin,Major\n", "utf-8")
    names, pairs = parse_ddinter(tmp_path)
    assert names == {"D1": "Warfarin", "D2": "Clarithromycin", "D3": "Lithium"}
    assert [(p.a, p.b, p.level) for p in pairs] == [("D1", "D2", "Major"), ("D1", "D3", "Unknown")]


class _FakeNeo4j:
    def __init__(self, co_mentions: list[str], sections: list[str]) -> None:
        self.co, self.sections = co_mentions, sections
        self.statements: list[str] = []

    def run(self, statement: str, **params: Any) -> list[dict[str, Any]]:
        self.statements.append(statement)
        if "INTERACTS_WITH" in statement:
            return [{"a": "Clarithromycin", "b": "Warfarin", "level": "Major", "source": "DDInter"}]
        if "hits >= 2" in statement:
            return [{"id": c} for c in self.co]
        return [{"id": c} for c in self.sections]


def test_graph_retriever_ranks_co_mentions_before_interaction_sections() -> None:
    client = _FakeNeo4j(["c1", "c2"], ["c2", "c3"])
    graph = GraphRetriever(client, LEX)  # type: ignore[arg-type]
    hits = graph.search(issue("warfarin with clarithromycin?", "synthetic-test-fixture"), k=20)
    assert [h.chunk_id for h in hits] == ["c1", "c2", "c3"]  # deduplicated, co-mentions first
    assert (
        graph.facts(issue("warfarin with clarithromycin?", "synthetic-test-fixture"))[0]["level"]
        == "Major"
    )
    client.statements.clear()
    assert graph.search(issue("usual warfarin dose?", "synthetic-test-fixture")) == []
    assert client.statements == []  # not routed: no graph query
    with pytest.raises(TypeError):
        graph.search("warfarin with clarithromycin")  # type: ignore[arg-type]


class _Pool:
    def search(self, query: DeidentifiedText, k: int = 10) -> list[Hit]:
        return [Hit(chunk_id=c, score=1.0) for c in ["a", "c2"][:k]]


def test_augmented_pool_appends_only_new_graph_candidates() -> None:
    graph = GraphRetriever(_FakeNeo4j(["c1", "c2"], []), LEX)  # type: ignore[arg-type]
    pool = GraphAugmentedPool(_Pool(), graph, base_depth=30, graph_depth=20)
    hits = pool.search(issue("warfarin with clarithromycin?", "synthetic-test-fixture"))
    assert [h.chunk_id for h in hits] == ["a", "c2", "c1"]
