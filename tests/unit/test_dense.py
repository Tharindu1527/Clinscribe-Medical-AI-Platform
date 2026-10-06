"""Dense index build and search, with an in-memory Qdrant and a fake encoder (no model download)."""

import hashlib
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray
from qdrant_client import QdrantClient

from privacy.deid.types import issue
from retrieval.dense import (
    DenseConfig,
    DenseRetriever,
    build_index,
    document_vectors,
    fingerprint,
    load_config,
    point_id,
)

CFG = DenseConfig(
    model="fake/model",
    revision="abc123",
    query_prefix="q: ",
    document_prefix="d: ",
    max_seq_length=128,
    batch_size=4,
    collection="test_dense",
)


class FakeEncoder:
    """Bag-of-words hashing: texts that share words get similar vectors."""

    dim = 64
    calls = 0

    def __init__(self, cfg: DenseConfig, prefix: str) -> None:
        self.prefix = prefix

    def encode(self, texts: list[str]) -> NDArray[np.float32]:
        FakeEncoder.calls += 1
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in text.lower().split():
                out[row, int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dim] += 1  # noqa: S324
        return np.asarray(out / np.linalg.norm(out, axis=1, keepdims=True), dtype=np.float32)


def _chunks() -> list[dict[str, str]]:
    texts = [
        "warfarin interacts with clarithromycin and raises the INR",
        "metformin is first line therapy for type 2 diabetes",
        "inhaled corticosteroids reduce asthma exacerbations",
    ]
    return [
        {
            "id": f"fda:x#s0#c{i}",
            "doc_id": "fda:x",
            "source": "openfda",
            "title": "T",
            "section": "S",
            "url": "https://example.org",
            "license": "CC0 1.0 (openFDA)",
            "topic": "t",
            "text": text,
        }
        for i, text in enumerate(texts)
    ]


def test_point_ids_are_stable_uuids() -> None:
    assert point_id("pmc:PMC1#s0#c0") == point_id("pmc:PMC1#s0#c0")
    assert point_id("pmc:PMC1#s0#c0") != point_id("pmc:PMC1#s0#c1")
    assert len(point_id("x")) == 36


def test_fingerprint_changes_with_corpus_model_or_revision() -> None:
    base = fingerprint(CFG, "sha-a")
    assert base == fingerprint(CFG, "sha-a")
    assert base != fingerprint(CFG, "sha-b")
    assert base != fingerprint(CFG.model_copy(update={"revision": "def456"}), "sha-a")
    assert base != fingerprint(CFG.model_copy(update={"model": "other/model"}), "sha-a")
    # the query prefix does not change document vectors, so it must not force a rebuild
    assert base == fingerprint(CFG.model_copy(update={"query_prefix": "x: "}), "sha-a")


def test_build_loads_every_chunk_then_skips_and_reuses_cached_vectors(tmp_path: Path) -> None:
    client = QdrantClient(":memory:")
    chunks = _chunks()
    FakeEncoder.calls = 0
    first = build_index(CFG, client, chunks, "sha-a", FakeEncoder, index_dir=tmp_path)
    assert (first["upserted"], first["cached"], FakeEncoder.calls) == (3, False, 1)
    assert client.get_collection(CFG.collection).points_count == 3

    second = build_index(CFG, client, chunks, "sha-a", FakeEncoder, index_dir=tmp_path)
    assert (second["upserted"], second["cached"], FakeEncoder.calls) == (0, True, 1)

    rebuilt = build_index(
        CFG, client, chunks, "sha-a", FakeEncoder, index_dir=tmp_path, recreate=True
    )
    assert (rebuilt["upserted"], rebuilt["cached"], FakeEncoder.calls) == (3, True, 1)

    changed = build_index(CFG, client, chunks[:2], "sha-b", FakeEncoder, index_dir=tmp_path)
    assert (changed["upserted"], changed["cached"], FakeEncoder.calls) == (2, False, 2)
    assert client.get_collection(CFG.collection).points_count == 2  # no stale points left


def test_search_ranks_the_matching_chunk_first_and_needs_deidentified_text(
    tmp_path: Path,
) -> None:
    client = QdrantClient(":memory:")
    build_index(CFG, client, _chunks(), "sha-a", FakeEncoder, index_dir=tmp_path)
    retriever = DenseRetriever(CFG, client, FakeEncoder(CFG, CFG.query_prefix))
    query = issue("does clarithromycin raise the INR on warfarin", "synthetic-test-fixture")
    hits = retriever.search(query, k=2)
    assert [h.chunk_id for h in hits][0] == "fda:x#s0#c0"
    assert hits[0].score >= hits[1].score
    with pytest.raises(TypeError):
        retriever.search("plain text", k=2)  # type: ignore[arg-type]


def test_repository_config_pins_a_model_revision() -> None:
    cfg = load_config()
    assert len(cfg.revision) == 40  # a full commit sha, not a branch name
    assert cfg.query_prefix.strip()
    assert cfg.document_prefix.strip()


def test_interrupted_embedding_resumes_from_the_last_finished_shard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("retrieval.dense.SHARD_SIZE", 1)  # one chunk per shard: 3 shards
    encoded: list[str] = []

    class FlakyEncoder(FakeEncoder):
        fail_after = 2

        def encode(self, texts: list[str]) -> NDArray[np.float32]:
            if len(encoded) == FlakyEncoder.fail_after:
                raise KeyboardInterrupt  # the session ends mid-run
            encoded.extend(texts)
            return super().encode(texts)

    with pytest.raises(KeyboardInterrupt):
        document_vectors(CFG, _chunks(), "sha-a", FlakyEncoder, index_dir=tmp_path)
    assert len(encoded) == 2

    FlakyEncoder.fail_after = -1
    vectors, meta = document_vectors(CFG, _chunks(), "sha-a", FlakyEncoder, index_dir=tmp_path)
    assert len(encoded) == 3  # only the missing shard was embedded
    assert (vectors.shape[0], meta["embedded_now"], meta["cached"]) == (3, 1, False)
    expected = FakeEncoder(CFG, "").encode([c["text"] for c in _chunks()])
    np.testing.assert_allclose(vectors, expected)
