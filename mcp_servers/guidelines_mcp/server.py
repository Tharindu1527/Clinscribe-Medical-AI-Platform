"""guidelines-mcp: cited evidence from the guideline corpus over MCP (Phase 3 task 2).

Tool
- search_guidelines: the top chunks for a query from the chosen Phase 2 pipeline (hybrid + ColBERT
  over the contextual corpus), as Evidence with chunk id, text, title, section, source and URL.
  Optional filters keep only some sources or topics (the pipeline searches deeper, then filters).

The query is sent through the de-ID service again before it reaches the encoders: the agent should
only hold de-identified text, and this keeps that true even if a caller gets it wrong (ADR-0001).
The returned text is the original chunk (not the contextual prefix the index was built with).

  uv run python -m mcp_servers.guidelines_mcp              (stdio; needs `just up` + `just up rag`)
  python -m mcp_servers.guidelines_mcp --http 0.0.0.0:8010 (streamable HTTP; the rag container)
"""

from collections.abc import Callable, Mapping
from typing import Any, Protocol

from mcp.server.mcpserver import MCPServer

from agents.schemas import Evidence, SearchGuidelinesInput
from privacy.deid.types import DeidentifiedText, issue
from retrieval.dense import Hit

FILTER_DEPTH = 50


class Searcher(Protocol):
    def search(self, query: DeidentifiedText, k: int = 10) -> list[Hit]: ...


def search(
    request: SearchGuidelinesInput,
    searcher: Searcher,
    chunks: Mapping[str, Mapping[str, Any]],
    deidentify: Callable[[str], DeidentifiedText],
) -> list[Evidence]:
    query = deidentify(request.query)
    filters = request.filters
    depth = FILTER_DEPTH if filters else request.k
    out = []
    for hit in searcher.search(query, k=depth):
        chunk = chunks[hit.chunk_id]
        if filters and filters.sources and chunk["source"] not in filters.sources:
            continue
        if filters and filters.topics and chunk.get("topic") not in filters.topics:
            continue
        out.append(
            Evidence(
                chunk_id=hit.chunk_id,
                text=chunk["text"],
                title=chunk["title"],
                section=chunk["section"],
                source=chunk["source"],
                source_url=chunk["url"],
                score=round(float(hit.score), 4),
            )
        )
        if len(out) == request.k:
            break
    return out


def build_server(
    searcher: Searcher,
    chunks: Mapping[str, Mapping[str, Any]],
    deidentify: Callable[[str], DeidentifiedText],
) -> MCPServer:
    server = MCPServer("guidelines-mcp", instructions="Cited evidence from clinical guidelines.")

    @server.tool()
    def search_guidelines(request: SearchGuidelinesInput) -> list[Evidence]:
        """Top guideline chunks for a question; cite their chunk_id in any answer."""
        return search(request, searcher, chunks, deidentify)

    return server


def main(argv: list[str] | None = None) -> None:
    from config.settings import Settings
    from mcp_servers.serve import http_address, run
    from privacy.deid.client import DeidClient
    from retrieval.dense import load_chunks
    from retrieval.pipeline import build_chosen

    address = http_address(argv, "guidelines-mcp")
    settings = Settings()
    deid = DeidClient(settings.deid_url)
    chunks = {c["id"]: c for c in load_chunks()[0]}  # original text, not the contextual variant
    searcher = build_chosen()
    # the first query loads model weights (~14 s cold without this); run it before the port opens,
    # so the healthcheck passes only once queries are fast
    searcher.search(issue("warm-up query about warfarin dosing", "synthetic-test-fixture"), k=1)
    server = build_server(
        searcher, chunks, lambda text: deid.deidentify(text, "guidelines-mcp").text
    )
    run(server, address)
