"""guidelines-mcp: cited evidence from the guideline corpus over MCP (Phase 3 task 2).

Tools
- search_guidelines: the top chunks for a query from the chosen Phase 2 pipeline (hybrid + ColBERT
  over the contextual corpus), as Evidence with chunk id, text, title, section, source and URL.
  Optional filters keep only some sources or topics (the pipeline searches deeper, then filters).
- check_grounding: is the question's subject in the sources (ADR-0018)? Question words the corpus
  never uses, and drugs the question names that the cited chunks do not (retrieval/grounding.py).

The query is sent through the de-ID service again before it reaches the encoders: the agent should
only hold de-identified text, and this keeps that true even if a caller gets it wrong (ADR-0001).
The returned text is the original chunk (not the contextual prefix the index was built with).

  uv run python -m mcp_servers.guidelines_mcp              (stdio; needs `just up` + `just up rag`)
  python -m mcp_servers.guidelines_mcp --http 0.0.0.0:8010 (streamable HTTP; the rag container)
"""

import os
import time
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from mcp.server.mcpserver import MCPServer

from agents.schemas import (
    CheckGroundingInput,
    Evidence,
    GroundingReport,
    SearchGuidelinesInput,
)
from privacy.deid.types import DeidentifiedText, issue
from retrieval.dense import Hit
from retrieval.grounding import Grounding

FILTER_DEPTH = 50


class Searcher(Protocol):
    def search(self, query: DeidentifiedText, k: int = 10) -> list[Hit]: ...


def _chaos_delay() -> None:
    """Incident drill only: CHAOS_SEARCH_DELAY_MS adds latency to every search."""
    delay = int(os.environ.get("CHAOS_SEARCH_DELAY_MS") or 0)
    if delay:
        time.sleep(delay / 1000)


def search(
    request: SearchGuidelinesInput,
    searcher: Searcher,
    chunks: Mapping[str, Mapping[str, Any]],
    deidentify: Callable[[str], DeidentifiedText],
) -> list[Evidence]:
    _chaos_delay()
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
    grounding: Grounding | None = None,
) -> MCPServer:
    server = MCPServer("guidelines-mcp", instructions="Cited evidence from clinical guidelines.")

    @server.tool()
    def search_guidelines(request: SearchGuidelinesInput) -> list[Evidence]:
        """Top guideline chunks for a question; cite their chunk_id in any answer."""
        return search(request, searcher, chunks, deidentify)

    if grounding is not None:

        @server.tool()
        def check_grounding(request: CheckGroundingInput) -> GroundingReport:
            """Question words the corpus never uses; with an answer's citations, also the drugs
            the question names that the cited chunks do not. Abstain or retry when non-empty."""
            question = deidentify(request.question).text
            missing = grounding.missing_drugs(question, request.cited) if request.cited else []
            return GroundingReport(
                unseen_terms=grounding.unseen_terms(question), missing_drugs=missing
            )

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
    corpus = load_chunks()[0]
    chunks = {c["id"]: c for c in corpus}  # original text, not the contextual variant
    searcher = build_chosen()
    # the first query loads model weights (~14 s cold without this); run it before the port opens,
    # so the healthcheck passes only once queries are fast
    searcher.search(issue("warm-up query about warfarin dosing", "synthetic-test-fixture"), k=1)
    import spacy

    from retrieval.graph.lexicon import DrugLexicon
    from retrieval.graph.load import GRAPH_DIR, read_jsonl

    # word vectors only: "is this a common English word" for check_grounding (no pipeline runs)
    english = spacy.load(settings.deid_spacy_model, exclude=["tagger", "parser", "ner",
                                                              "lemmatizer", "attribute_ruler",
                                                              "senter"]).vocab  # fmt: skip
    grounding = Grounding(
        corpus, english.has_vector, DrugLexicon(read_jsonl(GRAPH_DIR / "drugs.jsonl"))
    )
    server = build_server(
        searcher, chunks, lambda text: deid.deidentify(text, "guidelines-mcp").text, grounding
    )
    run(server, address)
