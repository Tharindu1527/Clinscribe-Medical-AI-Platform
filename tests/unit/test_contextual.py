"""Contextual-retrieval prefixes: prompt building, cleaning, resumable cache, output corpus."""

import json
from pathlib import Path
from typing import Any

import pytest

from retrieval.contextual import (
    clean,
    excerpts,
    generate_prefixes,
    load_prompt,
    messages_for,
    section_index,
    variant,
    write_variant,
)

DOCS = [
    {
        "id": "fda:x",
        "sections": [
            {"title": "Indications", "text": "Warfarin is indicated for prophylaxis " * 5},
            {"title": "Dosage", "text": "Start with 2 to 5 mg once daily."},
        ],
    }
]
CHUNKS = [
    {"id": "fda:x#s0#c0", "doc_id": "fda:x", "source": "openfda", "title": "Warfarin label",
     "section": "Indications", "text": "Warfarin is indicated for prophylaxis."},
    {"id": "fda:x#s0#c1", "doc_id": "fda:x", "source": "openfda", "title": "Warfarin label",
     "section": "Indications", "text": "It also reduces stroke risk."},
    {"id": "fda:x#s1#c0", "doc_id": "fda:x", "source": "openfda", "title": "Warfarin label",
     "section": "Dosage", "text": "Start with 2 to 5 mg once daily."},
]  # fmt: skip


def test_section_index_and_excerpts_follow_chunk_ids() -> None:
    assert section_index("pmc:PMC1#s12#c3") == 12
    found = excerpts(DOCS, words=3)
    assert found[("fda:x", 0)] == "Warfarin is indicated"
    assert found[("fda:x", 1)] == "Start with 2"


def test_chunks_of_one_section_share_the_prompt_up_to_the_chunk() -> None:
    spec = load_prompt()
    sections = excerpts(DOCS, spec.section_excerpt_words)
    _, first = messages_for(spec, CHUNKS[0], sections[("fda:x", 0)])
    _, second = messages_for(spec, CHUNKS[1], sections[("fda:x", 0)])
    shared = first.split("<chunk>")[0]
    assert second.startswith(shared)  # same prefix -> Ollama can reuse its cache
    assert 'source="FDA drug label"' in first
    assert "It also reduces stroke risk." in second


def test_clean_strips_preambles_quotes_and_long_outputs() -> None:
    assert clean('Here is the context: "Part of the warfarin label."', 60) == (
        "Part of the warfarin label."
    )
    assert clean("Context:\nDosage section\nof the label.", 60) == "Dosage section of the label."
    assert clean("one two three four", 2) == "one two"


def _fake(calls: list[str]) -> Any:
    def generate(system: str, user: str) -> dict[str, Any]:
        calls.append(user)
        return {"text": f"Context {len(calls)}.", "ms": 1.0, "in_tok": 10, "out_tok": 3}

    return generate


def test_prefix_cache_is_resumable_and_keyed_by_the_prompt(tmp_path: Path) -> None:
    spec = load_prompt()
    calls: list[str] = []
    cache = generate_prefixes(spec, "m", CHUNKS, DOCS, _fake(calls), tmp_path, limit=2)
    assert (len(calls), len(cache)) == (2, 2)  # pilot run
    cache = generate_prefixes(spec, "m", CHUNKS, DOCS, _fake(calls), tmp_path)
    assert (len(calls), len(cache)) == (3, 3)  # only the missing chunk was generated
    changed = spec.model_copy(update={"version": "2"})
    generate_prefixes(changed, "m", CHUNKS, DOCS, _fake(calls), tmp_path)
    assert len(calls) == 6  # a new prompt version regenerates everything


def test_variant_corpus_prepends_the_prefix_and_refuses_gaps(tmp_path: Path) -> None:
    spec = load_prompt()
    cache = generate_prefixes(spec, "m", CHUNKS, DOCS, _fake([]), tmp_path)
    manifest = write_variant(CHUNKS, cache, tmp_path, spec)
    rows = [json.loads(x) for x in (tmp_path / "chunks.jsonl").read_text("utf-8").splitlines()]
    assert rows[0]["text"] == "Context 1.\n\nWarfarin is indicated for prophylaxis."
    assert rows[0]["context"] == "Context 1."
    assert [r["id"] for r in rows] == [c["id"] for c in CHUNKS]  # same ids: golden set still valid
    assert manifest["chunks"] == 3
    assert len(manifest["chunks_sha256"]) == 64
    with pytest.raises(SystemExit, match="no prefix yet"):
        write_variant(CHUNKS, {"fda:x#s0#c0": cache["fda:x#s0#c0"]}, tmp_path, spec)


def test_variant_names() -> None:
    assert variant("raw")[1] == ""
    assert variant("contextual")[1] == f"_ctx_v{load_prompt().version}"
    with pytest.raises(ValueError, match="unknown corpus variant"):
        variant("other")
