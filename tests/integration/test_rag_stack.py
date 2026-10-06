"""PROGRESS Phase 2 task 2 gate: the rag profile is healthy and the dense index holds the corpus.

Needs `just up rag` and `just index`. Skipped when the rag profile is not running (Phase 1 gate and
CI start only core + fhir), unless CLINSCRIBE_REQUIRE_RAG=1.
"""

import os

import httpx
import pytest

from config.settings import Settings
from privacy.deid.types import issue
from retrieval.dense import (
    CORPUS,
    DenseRetriever,
    SentenceTransformerEncoder,
    connect,
    fingerprint,
    load_chunks,
    load_config,
)

QDRANT = "http://127.0.0.1:6333"
NEO4J_TX = "http://127.0.0.1:7474/db/neo4j/tx/commit"
RAG_SERVICES = {"qdrant", "neo4j"}


def _skip_or_fail(reason: str) -> None:
    if os.environ.get("CLINSCRIBE_REQUIRE_RAG") == "1":
        pytest.fail(reason)
    pytest.skip(reason)


@pytest.fixture(scope="module")
def rag(stack: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    by_name = {s["Service"]: s for s in stack}
    if not by_name.keys() >= RAG_SERVICES:
        _skip_or_fail("rag profile is not running (just up rag)")
    return by_name


def test_rag_services_running_and_healthy(rag: dict[str, dict[str, str]]) -> None:
    for name in RAG_SERVICES:
        assert rag[name]["State"] == "running", name
        assert rag[name].get("Health") == "healthy", name


def test_qdrant_is_ready_and_requires_the_api_key(rag: dict[str, dict[str, str]]) -> None:
    assert httpx.get(f"{QDRANT}/readyz", timeout=10).status_code == 200
    assert httpx.get(f"{QDRANT}/collections", timeout=10).status_code == 401
    key = Settings().qdrant_api_key.get_secret_value()
    response = httpx.get(f"{QDRANT}/collections", headers={"api-key": key}, timeout=10)
    assert response.status_code == 200


def test_neo4j_accepts_only_the_configured_login(rag: dict[str, dict[str, str]]) -> None:
    body = {"statements": [{"statement": "RETURN 1 AS ok"}]}
    password = Settings().neo4j_password.get_secret_value()
    response = httpx.post(NEO4J_TX, json=body, auth=("neo4j", password), timeout=30)
    assert response.status_code == 200, response.text[:200]
    assert response.json()["errors"] == []
    assert response.json()["results"][0]["data"][0]["row"] == [1]
    wrong = httpx.post(NEO4J_TX, json=body, auth=("neo4j", "not-the-password"), timeout=30)
    assert wrong.status_code == 401


@pytest.fixture(scope="module")
def corpus(rag: dict[str, dict[str, str]]) -> tuple[list[dict[str, str]], str]:
    if not (CORPUS / "manifest.json").exists():
        _skip_or_fail("no corpus built (just ingest)")
    return load_chunks()


def test_dense_index_holds_exactly_the_current_corpus(
    corpus: tuple[list[dict[str, str]], str],
) -> None:
    chunks, chunks_sha256 = corpus
    cfg = load_config()
    client = connect()
    if not client.collection_exists(cfg.collection):
        _skip_or_fail(f"collection {cfg.collection} not built (just index)")
    info = client.get_collection(cfg.collection)
    assert info.points_count == len(chunks)
    assert (info.config.metadata or {})["fingerprint"] == fingerprint(cfg, chunks_sha256)
    points, _ = client.scroll(cfg.collection, limit=5, with_payload=True)
    for point in points:
        payload = point.payload or {}
        assert payload["url"].startswith("https://")
        assert payload["section"]
        assert payload["text"]


def test_dense_search_answers_a_drug_question_from_the_label(
    corpus: tuple[list[dict[str, str]], str],
) -> None:
    """A smoke test only; retrieval quality is measured on the golden set (task 4)."""
    cfg = load_config()
    client = connect()
    if not client.collection_exists(cfg.collection):
        _skip_or_fail(f"collection {cfg.collection} not built (just index)")
    retriever = DenseRetriever(cfg, client, SentenceTransformerEncoder(cfg, cfg.query_prefix))
    query = issue("Which drugs increase the bleeding risk of warfarin?", "synthetic-test-fixture")
    hits = retriever.search(query, k=10)
    assert len(hits) == 10
    texts = {c["id"]: c["text"].lower() for c in corpus[0]}
    assert sum("warfarin" in texts[h.chunk_id] for h in hits) >= 5, hits
