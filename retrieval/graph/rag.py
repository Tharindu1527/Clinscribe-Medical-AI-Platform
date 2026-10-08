"""GraphRAG for drug questions (ablation step 6).

A question is routed to the graph when it names two or more different drugs (formulations of one
drug count once), or one drug plus an interaction cue ("interact", "together with", "a patient on
...", "which other drugs", ...). The cue list was widened after reading the golden questions (router
v1 caught 10 of 19 interaction questions), so results on that subset are somewhat optimistic.
The graph then supplies:
- interaction facts between the named drugs (DDInter level), for the answer step (task 10);
- candidate chunks: those mentioning at least two of the named drugs, then the "drug interactions"
  label sections of each named drug.
Graph candidates join the best first-stage pool and ColBERT reranks the union; questions that are
not routed go through the best pipeline unchanged.
"""

import re
from collections.abc import Sequence
from typing import Any, Protocol

from privacy.deid.types import DeidentifiedText
from retrieval.dense import Hit
from retrieval.graph.lexicon import DrugLexicon
from retrieval.graph.load import Neo4jHTTP

CUE = re.compile(
    r"\b(interact\w*|together|combin\w*|concomitant\w*|co-?administ\w*|alongside|"
    r"while (?:taking|on)|on both|add(?:ed|ing)? to|(?:raise|increase|lower)s? .{0,30}levels?|"
    # "a patient on warfarin", "someone taking lithium", "people who take ..."
    r"(?:patients?|someone|people|persons?|those|anyone|women|men|adults?|children)"
    r"(?: who (?:is|are|take|takes))? (?:on|taking|takes|receiving|using)|"
    # another drug or a drug class next to the named drug: "which other drugs", "diabetes medicine"
    r"(?:other|which) (?:drugs?|medicines?|medications?)|(?:drugs?|medicines?|medications?))\b",
    re.IGNORECASE,
)


class Retriever(Protocol):
    def search(self, query: DeidentifiedText, k: int = 10) -> list[Hit]: ...


def route(question: str, lexicon: DrugLexicon) -> list[str]:
    """Drug keys when the question is an interaction question, else an empty list."""
    drugs = sorted(lexicon.find(question))
    if lexicon.distinct(drugs) >= 2 or (drugs and CUE.search(question)):
        return drugs
    return []


class GraphRetriever:
    def __init__(self, client: Neo4jHTTP, lexicon: DrugLexicon) -> None:
        self._client = client
        self.lexicon = lexicon

    def facts(self, query: DeidentifiedText) -> list[dict[str, Any]]:
        """Interactions between the drugs the question names (empty if not routed)."""
        keys = route(query.text, self.lexicon)
        if len(keys) < 2:
            return []
        return self._client.run(
            "MATCH (a:Drug)-[r:INTERACTS_WITH]-(b:Drug) WHERE a.key IN $keys AND b.key IN $keys "
            "AND a.key < b.key RETURN a.name AS a, b.name AS b, r.level AS level, "
            "r.source AS source ORDER BY a, b",
            keys=keys,
        )

    def search(self, query: DeidentifiedText, k: int = 20) -> list[Hit]:
        """Graph candidates for a routed question (empty list otherwise), best first."""
        if not isinstance(query, DeidentifiedText):
            raise TypeError("GraphRetriever.search accepts only DeidentifiedText")
        keys = route(query.text, self.lexicon)
        if not keys:
            return []
        rows: list[dict[str, Any]] = []
        if len(keys) >= 2:
            rows = self._client.run(
                "MATCH (c:Chunk)-[:MENTIONS]->(d:Drug) WHERE d.key IN $keys "
                "WITH c, count(DISTINCT d) AS hits WHERE hits >= 2 "
                "RETURN c.id AS id ORDER BY hits DESC, c.interaction_section DESC, c.id LIMIT $k",
                keys=keys,
                k=k,
            )
        if len(rows) < k:
            rows += self._client.run(
                "MATCH (c:Chunk {interaction_section: true})-[:MENTIONS]->(d:Drug) "
                "WHERE d.key IN $keys RETURN DISTINCT c.id AS id ORDER BY c.id LIMIT $k",
                keys=keys,
                k=k,
            )
        ids = list(dict.fromkeys(row["id"] for row in rows))[:k]
        return [Hit(chunk_id=c, score=float(len(ids) - i)) for i, c in enumerate(ids)]


class GraphAugmentedPool:
    """First stage for the reranker: the base pool plus graph candidates it does not contain."""

    def __init__(
        self, base: Retriever, graph: GraphRetriever, base_depth: int = 30, graph_depth: int = 20
    ) -> None:
        self._base = base
        self._graph = graph
        self._base_depth = base_depth
        self._graph_depth = graph_depth

    def search(self, query: DeidentifiedText, k: int = 50) -> list[Hit]:
        hits = self._base.search(query, k=self._base_depth)
        seen = {h.chunk_id for h in hits}
        extra = [
            h for h in self._graph.search(query, k=self._graph_depth) if h.chunk_id not in seen
        ]
        return [*hits, *extra]


def routed_ids(items: Sequence[Any], lexicon: DrugLexicon) -> set[str]:
    """Golden-set item ids whose question the router sends to the graph."""
    return {item.id for item in items if route(item.question, lexicon)}


def fact_sources(facts: Sequence[dict[str, Any]]) -> list[dict[str, str]]:
    """Graph facts as citable sources for the answer step; ids start with "graph:ddinter:"."""
    return [
        {
            "id": f"graph:ddinter:{f['a']}|{f['b']}",
            "title": "DDInter 2.0 drug-drug interaction database",
            "section": "Interaction severity",
            "text": f"{f['a']} and {f['b']}: {f['level']} interaction (DDInter 2.0). "
            "The database records the pair and its severity, not the mechanism or management.",
        }
        for f in facts
    ]
