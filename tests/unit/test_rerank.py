"""ColBERT encoding rules, MaxSim, the document store and rerank plumbing (no model download)."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from transformers import BertTokenizer

from privacy.deid.types import DeidentifiedText, issue
from retrieval.colbert import ColBERTConfig, ColBERTEncoder, DocStore, build_store, maxsim
from retrieval.dense import Hit
from retrieval.rerank import RerankedRetriever, _ordered

VOCAB = ["[PAD]", "[unused0]", "[unused1]", "[UNK]", "[CLS]", "[SEP]", "[MASK]", ".", ",", "?",
         "warfarin", "dose", "risk"]  # fmt: skip


def _encoder(query_maxlen: int = 8) -> ColBERTEncoder:
    enc = object.__new__(ColBERTEncoder)  # skip model loading; test the tokenisation rules
    # transformers 5 builds the vocabulary from a mapping (a vocab_file argument is ignored)
    enc.tokenizer = BertTokenizer(vocab={w: i for i, w in enumerate(VOCAB)})
    enc.query_maxlen, enc.doc_maxlen = query_maxlen, 16
    enc.attend_to_mask_tokens = False
    enc.q_marker = VOCAB.index("[unused0]")
    enc.d_marker = VOCAB.index("[unused1]")
    enc.skiplist = {VOCAB.index(p) for p in ".,?"}
    enc._batch_size = 4
    return enc


def test_query_gets_q_marker_and_mask_augmentation_without_attention() -> None:
    enc = _encoder()
    ids, mask = enc.query_inputs(["warfarin dose?"])
    tokens = [VOCAB[i] for i in ids[0].tolist()]
    assert tokens == ["[CLS]", "[unused0]", "warfarin", "dose", "?", "[SEP]", "[MASK]", "[MASK]"]
    assert mask[0].tolist() == [1, 1, 1, 1, 1, 1, 0, 0]  # padding became [MASK], not attended


def test_document_gets_d_marker_and_drops_padding_and_punctuation() -> None:
    enc = _encoder()
    ids, _ = enc.doc_inputs(["warfarin risk, dose.", "dose"])
    assert [VOCAB[i] for i in ids[0].tolist()][:3] == ["[CLS]", "[unused1]", "warfarin"]

    def fake_embed(ids: Any, mask: Any) -> Any:  # token id as a 1-d "embedding"
        return ids.unsqueeze(-1).float()

    enc._embed = fake_embed  # type: ignore[method-assign]
    docs = enc.encode_docs(["warfarin risk, dose.", "dose"])
    kept = [[VOCAB[int(v)] for v in d[:, 0]] for d in docs]
    assert kept[0] == ["[CLS]", "[unused1]", "warfarin", "risk", "dose", "[SEP]"]
    assert kept[1] == ["[CLS]", "[unused1]", "dose", "[SEP]"]  # padding removed
    assert docs[0].dtype == np.float16


def test_maxsim_hand_worked() -> None:
    query = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    doc = np.array([[0.6, 0.8], [1.0, 0.0]], dtype=np.float16)
    # token 1: max(0.6, 1.0) = 1.0; token 2: max(0.8, 0.0) = 0.8
    assert maxsim(query, doc) == pytest.approx(1.8, abs=1e-3)  # float16 storage
    assert maxsim(query, np.zeros((0, 2), dtype=np.float16)) == 0.0


def test_doc_store_slices_by_offsets() -> None:
    vectors = np.arange(10, dtype=np.float16).reshape(5, 2)
    store = DocStore(["a", "b"], vectors, np.array([0, 2, 5]))
    assert store.get("a").tolist() == [[0, 1], [2, 3]]
    assert len(store.get("b")) == 3
    assert "b" in store
    assert "c" not in store


class _FakeColBERT:
    calls = 0

    def __init__(self, cfg: ColBERTConfig) -> None:
        pass

    def encode_docs(self, texts: list[str]) -> list[Any]:
        _FakeColBERT.calls += 1
        return [np.full((len(t.split()), 2), 0.5, dtype=np.float16) for t in texts]


def test_store_build_is_resumable_and_maps_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("retrieval.colbert.SHARD_SIZE", 1)
    cfg = ColBERTConfig(model="fake/colbert", revision="abc123456789xyz")
    chunks = [{"id": "c0", "text": "one two"}, {"id": "c1", "text": "three"}]
    store, meta = build_store(cfg, chunks, "sha", _FakeColBERT, index_dir=tmp_path)
    assert (meta["chunks"], meta["tokens"], _FakeColBERT.calls) == (2, 3, 2)
    assert store.get("c1").shape == (1, 2)
    build_store(cfg, chunks, "sha", _FakeColBERT, index_dir=tmp_path)
    assert _FakeColBERT.calls == 2  # cached: nothing re-encoded


def test_rerank_order_is_by_score_and_stable_on_ties() -> None:
    hits = _ordered(["a", "b", "c"], [0.1, 0.9, 0.1])
    assert [h.chunk_id for h in hits] == ["b", "a", "c"]


class _Pool:
    def __init__(self) -> None:
        self.depths: list[int] = []

    def search(self, query: DeidentifiedText, k: int = 10) -> list[Hit]:
        self.depths.append(k)
        return [Hit(chunk_id=f"c{i}", score=1.0) for i in range(k)]


class _Reverse:
    def rerank(self, query: DeidentifiedText, candidates: Sequence[Hit]) -> list[Hit]:
        return list(reversed(candidates))


def test_reranked_retriever_reorders_the_first_stage_pool() -> None:
    pool = _Pool()
    retriever = RerankedRetriever(pool, _Reverse(), depth=30)
    hits = retriever.search(issue("question", "synthetic-test-fixture"), k=3)
    assert [h.chunk_id for h in hits] == ["c29", "c28", "c27"]
    assert pool.depths == [30]
    with pytest.raises(TypeError):
        retriever.search("question", k=3)  # type: ignore[arg-type]
