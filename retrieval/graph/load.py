"""Load the drug graph into Neo4j through its HTTP transaction API (no driver dependency).

Idempotent: a (:Meta) node stores the fingerprint of the loaded data; when it matches, nothing is
reloaded. Which names count as drugs is decided by the lexicon (retrieval/graph/lexicon.py).
"""

import hashlib
import json
import re
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx

from config.settings import Settings
from retrieval.graph.lexicon import DrugLexicon

ROOT = Path(__file__).resolve().parents[2]
GRAPH_DIR = ROOT / "data" / "graph"
CORPUS = ROOT / "data" / "corpus"
NEO4J_HTTP = "http://127.0.0.1:7474"
INTERACTION_SECTION = re.compile(r"interaction", re.IGNORECASE)
BATCH = 5000


class Neo4jHTTP:
    def __init__(self, url: str = NEO4J_HTTP, settings: Settings | None = None) -> None:
        password = (settings or Settings()).neo4j_password.get_secret_value()
        self._http = httpx.Client(base_url=url, auth=("neo4j", password), timeout=300)

    def run(self, statement: str, **parameters: Any) -> list[dict[str, Any]]:
        """Run one statement; rows as dicts keyed by the RETURN columns."""
        body = {"statements": [{"statement": statement, "parameters": parameters}]}
        response = self._http.post("/db/neo4j/tx/commit", json=body)
        response.raise_for_status()
        data = response.json()
        if data["errors"]:
            raise RuntimeError(data["errors"][0]["message"])
        result = data["results"][0]
        return [dict(zip(result["columns"], row["row"], strict=True)) for row in result["data"]]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def mentions(lexicon: DrugLexicon, chunks: Sequence[dict[str, str]]) -> list[tuple[str, str]]:
    """(chunk id, drug key) for every drug each chunk names."""
    return sorted((c["id"], key) for c in chunks for key in lexicon.find(c["text"]))


def load_graph(client: Neo4jHTTP | None = None) -> dict[str, Any]:
    client = client or Neo4jHTTP()
    drugs = read_jsonl(GRAPH_DIR / "drugs.jsonl")
    interactions = read_jsonl(GRAPH_DIR / "interactions.jsonl")
    chunks = read_jsonl(CORPUS / "chunks.jsonl")
    lexicon = DrugLexicon(drugs)
    edges = mentions(lexicon, chunks)
    fingerprint = hashlib.sha256(
        json.dumps([drugs, interactions, edges]).encode("utf-8")
    ).hexdigest()
    stored = client.run("MATCH (m:Meta {name: 'drug_graph'}) RETURN m.fingerprint AS fp")
    if stored and stored[0]["fp"] == fingerprint:
        return {"loaded": False, **counts(client)}
    started = time.perf_counter()
    while client.run("MATCH (n) WITH n LIMIT 20000 DETACH DELETE n RETURN count(*) AS n")[0]["n"]:
        pass
    client.run("CREATE CONSTRAINT drug_key IF NOT EXISTS FOR (d:Drug) REQUIRE d.key IS UNIQUE")
    client.run("CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.id IS UNIQUE")
    rows = [
        {
            "key": d["ddinter_id"],
            "name": d["name"],
            "rxcui": d["rxcui"],
            "ingredient": d["ingredient"],
            "brands": d["brands"],
        }
        for d in drugs
    ]
    for start in range(0, len(rows), BATCH):
        client.run(
            "UNWIND $rows AS r CREATE (:Drug {key: r.key, name: r.name, rxcui: r.rxcui, "
            "ingredient: r.ingredient, brands: r.brands})",
            rows=rows[start : start + BATCH],
        )
    for start in range(0, len(interactions), BATCH):
        client.run(
            "UNWIND $rows AS r MATCH (a:Drug {key: r.a}), (b:Drug {key: r.b}) "
            "CREATE (a)-[:INTERACTS_WITH {level: r.level, source: 'DDInter 2.0'}]->(b)",
            rows=interactions[start : start + BATCH],
        )
    chunk_rows = [
        {
            "id": c["id"],
            "doc_id": c["doc_id"],
            "section": c["section"],
            "ix": bool(INTERACTION_SECTION.search(c["section"])),
        }
        for c in chunks
    ]
    for start in range(0, len(chunk_rows), BATCH):
        client.run(
            "UNWIND $rows AS r CREATE (:Chunk {id: r.id, doc_id: r.doc_id, "
            "section: r.section, interaction_section: r.ix})",
            rows=chunk_rows[start : start + BATCH],
        )
    edge_rows = [{"c": c, "d": d} for c, d in edges]
    for start in range(0, len(edge_rows), BATCH):
        client.run(
            "UNWIND $rows AS r MATCH (c:Chunk {id: r.c}), (d:Drug {key: r.d}) "
            "CREATE (c)-[:MENTIONS]->(d)",
            rows=edge_rows[start : start + BATCH],
        )
    client.run("CREATE (:Meta {name: 'drug_graph', fingerprint: $fp})", fp=fingerprint)
    return {
        "loaded": True,
        "load_seconds": round(time.perf_counter() - started, 1),
        **counts(client),
    }


def counts(client: Neo4jHTTP) -> dict[str, Any]:
    levels = client.run(
        "MATCH ()-[r:INTERACTS_WITH]->() RETURN r.level AS level, count(*) AS n ORDER BY level"
    )
    return {
        "drugs": client.run("MATCH (d:Drug) RETURN count(d) AS n")[0]["n"],
        "interactions": sum(row["n"] for row in levels),
        "interactions_by_level": {row["level"]: row["n"] for row in levels},
        "chunks": client.run("MATCH (c:Chunk) RETURN count(c) AS n")[0]["n"],
        "mentions": client.run("MATCH ()-[m:MENTIONS]->() RETURN count(m) AS n")[0]["n"],
        "chunks_with_mentions": client.run(
            "MATCH (c:Chunk)-[:MENTIONS]->() RETURN count(DISTINCT c) AS n"
        )[0]["n"],
    }
