"""druggraph-mcp: drug-drug interactions from the DDInter graph over MCP (Phase 3 task 2).

Tool
- check_interactions: the interactions (with DDInter severity) among the named drugs, and the names
  that matched no drug in the graph. Names are matched with the Phase 2 lexicon (generic names,
  salt-free forms, capitalised brands). Each interaction carries a citable id
  ("graph:ddinter:A|B", the same form the answer step cites, retrieval/graph/rag.py).

  uv run python -m mcp_servers.druggraph_mcp     (stdio; needs `just up rag` and `just graph`)
"""

from typing import Any, Protocol

from mcp.server.mcpserver import MCPServer

from agents.schemas import CheckInteractionsInput, Interaction, InteractionReport
from retrieval.graph.lexicon import DrugLexicon

QUERY = (
    "MATCH (a:Drug)-[r:INTERACTS_WITH]-(b:Drug) WHERE a.key IN $keys AND b.key IN $keys "
    "AND a.key < b.key RETURN a.name AS a, b.name AS b, r.level AS level ORDER BY a, b"
)


class Graph(Protocol):
    def run(self, statement: str, **params: Any) -> list[dict[str, Any]]: ...


def check(request: CheckInteractionsInput, graph: Graph, lexicon: DrugLexicon) -> InteractionReport:
    keys: set[str] = set()
    unknown = []
    for name in request.drugs:
        found = lexicon.find(name)
        if found:
            keys |= found
        else:
            unknown.append(name)
    rows = graph.run(QUERY, keys=sorted(keys)) if lexicon.distinct(keys) >= 2 else []
    interactions = [
        Interaction(
            drug_a=row["a"],
            drug_b=row["b"],
            severity=row["level"],
            source_id=f"graph:ddinter:{row['a']}|{row['b']}",
        )
        for row in rows
        if row["a"].split(" (")[0].lower() != row["b"].split(" (")[0].lower()
    ]
    return InteractionReport(interactions=interactions, unknown_drugs=unknown)


def build_server(graph: Graph, lexicon: DrugLexicon) -> MCPServer:
    server = MCPServer("druggraph-mcp", instructions="Drug-drug interactions (DDInter 2.0).")

    @server.tool()
    def check_interactions(request: CheckInteractionsInput) -> InteractionReport:
        """Interactions among the named drugs, with severity; also lists names not in the graph."""
        return check(request, graph, lexicon)

    return server


def main() -> None:
    from retrieval.graph.load import GRAPH_DIR, Neo4jHTTP, read_jsonl

    build_server(Neo4jHTTP(), DrugLexicon(read_jsonl(GRAPH_DIR / "drugs.jsonl"))).run("stdio")
