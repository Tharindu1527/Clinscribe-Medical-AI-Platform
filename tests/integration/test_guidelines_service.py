"""PROGRESS Phase 3 task 3 gate: guidelines-mcp runs as its own container (the only image with
torch) and answers search_guidelines over streamable HTTP.

Needs `just up rag`; skipped otherwise unless CLINSCRIBE_REQUIRE_RAG=1.
"""

import os
from typing import Any

import anyio
import pytest
from mcp import Client

URL = "http://127.0.0.1:8010/mcp"


@pytest.fixture(scope="module")
def service(stack: list[dict[str, str]]) -> str:
    running = any(
        s.get("Service") == "guidelines-mcp" and s.get("State") == "running" for s in stack
    )
    if not running:
        if os.environ.get("CLINSCRIBE_REQUIRE_RAG") == "1":
            pytest.fail("guidelines-mcp is not running (just up rag)")
        pytest.skip("guidelines-mcp is not running (just up rag)")
    return URL


def _search(url: str, request: dict[str, Any]) -> tuple[bool, Any]:
    async def run() -> tuple[bool, Any]:
        async with Client(url, read_timeout_seconds=120) as client:
            tools = [t.name for t in (await client.list_tools()).tools]
            assert tools == ["search_guidelines"]
            result = await client.call_tool("search_guidelines", {"request": request})
            text = " ".join(getattr(c, "text", "") for c in result.content)
            return result.is_error, (text if result.is_error else result.structured_content)

    return anyio.run(run)


def test_search_over_http_returns_cited_evidence(service: str) -> None:
    error, result = _search(service, {"query": "Which inhaler is first-line for asthma?", "k": 3})
    assert not error, result
    evidence = result["result"]
    assert len(evidence) == 3
    for item in evidence:
        assert item["chunk_id"].split(":", 1)[0] in {"who", "fda", "pmc"}
        assert item["source_url"].startswith("https://")


def test_invalid_requests_are_rejected_by_the_contract(service: str) -> None:
    error, message = _search(service, {"query": "hi", "k": 3})  # shorter than 3 characters
    assert error
    assert "query" in message
