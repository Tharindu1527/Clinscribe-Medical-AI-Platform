"""PROGRESS Phase 2 task 3 gate: the golden set is valid against the built corpus.

Every gold chunk exists and contains the quoted answer, no question copies its source, every
unanswerable item's terms are absent from the corpus. Needs `just ingest`; skipped without a corpus
unless CLINSCRIBE_REQUIRE_RAG=1.
"""

import os

import pytest

from evals.golden.golden import CORPUS_CHUNKS, expand, load_chunks, load_items, validate


def test_golden_set_is_valid_and_gold_ids_are_current() -> None:
    if not CORPUS_CHUNKS.exists():
        if os.environ.get("CLINSCRIBE_REQUIRE_RAG") == "1":
            pytest.fail("no corpus built (just ingest)")
        pytest.skip("no corpus built (just ingest)")
    items, chunks = load_items(), load_chunks()
    assert validate(items, chunks) == []
    # gold ids are all chunks containing the quote; a corpus rebuild must be followed by --expand
    assert [i.gold_chunk_ids for i in expand(items, chunks)] == [i.gold_chunk_ids for i in items]
