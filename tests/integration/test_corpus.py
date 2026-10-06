"""PROGRESS Phase 2 task 1 gate: the built corpus is citable, licensed, de-duplicated, reproducible.

Needs `just ingest` first. Skipped when no corpus has been built (CI does not build one), unless
CLINSCRIBE_REQUIRE_RAG=1 (the Phase 2 gate).
"""

import json
import os
import re
from pathlib import Path

import pytest

from retrieval.ingest.models import content_hash, garbled_share
from retrieval.ingest.pipeline import DATA, GARBLED_THRESHOLD, build, load_config

ALLOWED_LICENCE = re.compile(r"^(CC BY \d\.\d|CC0 1\.0|CC0 1\.0 \(openFDA\)|CC BY-NC-SA 3\.0 IGO)$")


@pytest.fixture(scope="module")
def corpus() -> dict[str, list[dict[str, str]]]:
    if not (DATA / "manifest.json").exists():
        if os.environ.get("CLINSCRIBE_REQUIRE_RAG") == "1":
            pytest.fail("no corpus built (just ingest)")
        pytest.skip("no corpus built (just ingest)")

    def rows(name: str) -> list[dict[str, str]]:
        lines = (DATA / name).read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines]

    return {"docs": rows("docs.jsonl"), "chunks": rows("chunks.jsonl")}


def test_corpus_size_and_sources(corpus: dict[str, list[dict[str, str]]]) -> None:
    docs = corpus["docs"]
    assert len(docs) >= 150, len(docs)  # plan: ~200-400 documents
    assert {d["source"] for d in docs} == {"who", "openfda", "pmc"}
    assert 3_000 <= len(corpus["chunks"]) <= 15_000, len(corpus["chunks"])


def test_every_chunk_is_citable_and_licensed(corpus: dict[str, list[dict[str, str]]]) -> None:
    doc_ids = {d["id"] for d in corpus["docs"]}
    for chunk in corpus["chunks"]:
        assert chunk["url"].startswith("https://"), chunk["id"]
        assert chunk["section"].strip(), chunk["id"]
        assert chunk["doc_id"] in doc_ids, chunk["id"]
        assert ALLOWED_LICENCE.match(chunk["license"]), (chunk["id"], chunk["license"])


def test_text_is_readable(corpus: dict[str, list[dict[str, str]]]) -> None:
    """Broken PDF font decoding ("'L΍HUHQWLDO") must not reach the index."""
    garbled = [c["id"] for c in corpus["chunks"] if garbled_share(c["text"]) > GARBLED_THRESHOLD]
    assert len(garbled) <= 0.005 * len(corpus["chunks"]), garbled[:10]


def test_no_veterinary_or_combination_mismatches(corpus: dict[str, list[dict[str, str]]]) -> None:
    titles = [d["title"].lower() for d in corpus["docs"]]
    assert not [t for t in titles if re.search(r"\b(equine|canine|feline|veterinary)\b", t)]
    assert not [t for t in titles if "voquezna" in t]  # an H. pylori kit is not "clarithromycin"


def test_no_duplicate_ids_or_texts(corpus: dict[str, list[dict[str, str]]]) -> None:
    chunks = corpus["chunks"]
    assert len({c["id"] for c in chunks}) == len(chunks)
    assert len({content_hash(c["text"]) for c in chunks}) == len(chunks)
    assert len({d["id"] for d in corpus["docs"]}) == len(corpus["docs"])


def test_rebuild_from_raw_cache_is_byte_identical(
    corpus: dict[str, list[dict[str, str]]], tmp_path: Path
) -> None:
    built = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    rebuilt = build(load_config(), tmp_path, DATA / "raw", offline=True)
    assert rebuilt["docs_sha256"] == built["docs_sha256"]
    assert rebuilt["chunks_sha256"] == built["chunks_sha256"]
