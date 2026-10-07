"""ColBERT late-interaction scoring for reranking (ablation step 3), Stanford ColBERT format.

Implements the encoding of the original ColBERT code for checkpoints such as
answerdotai/answerai-colbert-small-v1, so no ColBERT library is needed (PyLate pins older
sentence-transformers/transformers versions; see ADR-0006):
- query: ". " + text, the "." replaced by the [Q] marker, padded to query_maxlen with [MASK]
  (query augmentation: [MASK] positions get no attention but their embeddings are scored);
- document: ". " + text, the "." replaced by the [D] marker, truncated to doc_maxlen; padding
  and punctuation tokens are dropped;
- BERT -> linear projection (no bias) -> L2 normalisation; score = sum over query tokens of the
  best cosine similarity among the document tokens (MaxSim).

Document embeddings are computed once for the corpus and cached on D: in resumable shards
(`just index-colbert`), as a deployment would precompute them.

Usage: uv run python -m retrieval.colbert   (builds data/index/colbert-<revision>/)
"""

import argparse
import json
import string
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from numpy.typing import NDArray
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
INDEX_DIR = ROOT / "data" / "index"
SHARD_SIZE = 512


class ColBERTConfig(BaseModel):
    model: str
    revision: str
    batch_size: int = 32


def load_config(path: Path = ROOT / "config" / "retrieval.yaml") -> ColBERTConfig:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ColBERTConfig.model_validate(cfg["rerank"]["colbert"])


class ColBERTEncoder:
    def __init__(self, cfg: ColBERTConfig, device: str = "cpu") -> None:
        import torch  # heavy: lazy
        from huggingface_hub import snapshot_download
        from safetensors.torch import load_file
        from transformers import AutoTokenizer, BertModel

        path = Path(
            snapshot_download(
                cfg.model,
                revision=cfg.revision,
                allow_patterns=["*.json", "model.safetensors", "vocab.txt", "artifact.metadata"],
            )
        )
        meta: dict[str, Any] = json.loads((path / "artifact.metadata").read_text(encoding="utf-8"))
        if meta.get("similarity") != "cosine" or meta.get("interaction") != "colbert":
            raise ValueError("only cosine ColBERT checkpoints are supported")
        self.query_maxlen = int(meta["query_maxlen"])
        self.doc_maxlen = int(meta["doc_maxlen"])
        self.attend_to_mask_tokens = bool(meta["attend_to_mask_tokens"])
        self._torch = torch
        self._device = device
        self._batch_size = cfg.batch_size
        self.tokenizer = AutoTokenizer.from_pretrained(path)
        bert: Any = BertModel.from_pretrained(path, add_pooling_layer=False)  # loose HF typing
        bert.to(torch.device(device))
        self.bert = bert.eval()
        weight = load_file(str(path / "model.safetensors"))["linear.weight"]
        self.linear = torch.nn.Linear(weight.shape[1], weight.shape[0], bias=False)
        self.linear.weight = torch.nn.Parameter(weight, requires_grad=False)
        self.linear.to(device)
        self.dim = int(weight.shape[0])
        tok = self.tokenizer
        self.q_marker = tok.convert_tokens_to_ids(meta["query_token_id"])
        self.d_marker = tok.convert_tokens_to_ids(meta["doc_token_id"])
        self.skiplist = (
            {tok.encode(p, add_special_tokens=False)[0] for p in string.punctuation}
            if meta.get("mask_punctuation")
            else set()
        )

    def _embed(self, ids: Any, mask: Any) -> Any:
        torch = self._torch
        with torch.inference_mode():
            hidden = self.bert(input_ids=ids.to(self._device), attention_mask=mask.to(self._device))
            out = self.linear(hidden.last_hidden_state)
            return torch.nn.functional.normalize(out, p=2, dim=2).cpu()

    def query_inputs(self, texts: Sequence[str]) -> tuple[Any, Any]:
        tok = self.tokenizer
        enc = tok(
            [". " + t for t in texts],
            padding="max_length",
            truncation=True,
            max_length=self.query_maxlen,
            return_tensors="pt",
        )
        ids, mask = enc["input_ids"], enc["attention_mask"]
        ids[:, 1] = self.q_marker
        ids[ids == tok.pad_token_id] = tok.mask_token_id
        if self.attend_to_mask_tokens:
            mask[ids == tok.mask_token_id] = 1
        return ids, mask

    def doc_inputs(self, texts: Sequence[str]) -> tuple[Any, Any]:
        enc = self.tokenizer(
            [". " + t for t in texts],
            padding="longest",
            truncation=True,
            max_length=self.doc_maxlen,
            return_tensors="pt",
        )
        ids, mask = enc["input_ids"], enc["attention_mask"]
        ids[:, 1] = self.d_marker
        return ids, mask

    def encode_queries(self, texts: Sequence[str]) -> list[NDArray[np.float32]]:
        """One (query_maxlen, dim) matrix per query; [MASK] augmentation tokens included."""
        ids, mask = self.query_inputs(texts)
        return [q.numpy().astype(np.float32) for q in self._embed(ids, mask)]

    def encode_docs(self, texts: Sequence[str]) -> list[NDArray[np.float16]]:
        """One (kept_tokens, dim) matrix per document: padding and punctuation removed."""
        out: list[NDArray[np.float16]] = []
        for start in range(0, len(texts), self._batch_size):
            ids, mask = self.doc_inputs(texts[start : start + self._batch_size])
            vectors = self._embed(ids, mask)
            for row_ids, row_mask, row in zip(ids, mask, vectors, strict=True):
                keep = [
                    bool(m) and int(t) not in self.skiplist
                    for t, m in zip(row_ids.tolist(), row_mask.tolist(), strict=True)
                ]
                out.append(row[keep].numpy().astype(np.float16))
        return out


def maxsim(query: NDArray[np.float32], doc: NDArray[np.floating[Any]]) -> float:
    """Sum over query tokens of the best cosine similarity among the document tokens."""
    if len(doc) == 0:
        return 0.0
    return float((query @ doc.astype(np.float32).T).max(axis=1).sum())


class DocStore:
    """Precomputed document token embeddings: one flat float16 matrix plus row offsets."""

    def __init__(self, chunk_ids: Sequence[str], vectors: NDArray[Any], offsets: NDArray[Any]):
        self._row = {cid: i for i, cid in enumerate(chunk_ids)}
        self._vectors = vectors
        self._offsets = offsets

    def get(self, chunk_id: str) -> NDArray[Any]:
        i = self._row[chunk_id]
        return self._vectors[self._offsets[i] : self._offsets[i + 1]]

    def __contains__(self, chunk_id: object) -> bool:
        return chunk_id in self._row


def store_dir(cfg: ColBERTConfig, chunks_sha256: str, index_dir: Path = INDEX_DIR) -> Path:
    return index_dir / f"colbert-{cfg.revision[:12]}-{chunks_sha256[:12]}"


def build_store(
    cfg: ColBERTConfig,
    chunks: Sequence[dict[str, str]],
    chunks_sha256: str,
    encoder_factory: Any,
    index_dir: Path = INDEX_DIR,
) -> tuple[DocStore, dict[str, Any]]:
    """Encode every chunk once (resumable per shard) and load the store memory-mapped."""
    folder = store_dir(cfg, chunks_sha256, index_dir)
    folder.mkdir(parents=True, exist_ok=True)
    ids = [c["id"] for c in chunks]
    meta_path = folder / "meta.json"
    if not meta_path.exists():
        encoder = None
        seconds, encoded = 0.0, 0
        starts = range(0, len(chunks), SHARD_SIZE)
        for number, start in enumerate(starts):
            shard = folder / f"{number:05d}.npz"
            if shard.exists():
                continue
            encoder = encoder or encoder_factory(cfg)
            batch = chunks[start : start + SHARD_SIZE]
            began = time.perf_counter()
            docs = encoder.encode_docs([c["text"] for c in batch])
            seconds += time.perf_counter() - began
            encoded += len(batch)
            lengths = np.array([len(d) for d in docs], dtype=np.int64)
            np.savez(shard, vectors=np.concatenate(docs), lengths=lengths)
            rate = encoded / seconds if seconds else 0.0
            print(f"shard {number + 1}/{len(starts)}: {rate:.1f} chunks/s", file=sys.stderr)
        parts = [np.load(folder / f"{n:05d}.npz") for n in range(len(starts))]
        vectors = np.concatenate([p["vectors"] for p in parts])
        lengths = np.concatenate([p["lengths"] for p in parts])
        offsets = np.concatenate([[0], np.cumsum(lengths)]).astype(np.int64)
        np.save(folder / "vectors.npy", vectors)
        np.save(folder / "offsets.npy", offsets)
        meta = {
            "model": cfg.model,
            "revision": cfg.revision,
            "chunks": len(ids),
            "tokens": int(offsets[-1]),
            "megabytes": round(vectors.nbytes / 1e6),
            "encoded_now": encoded,
            "encode_seconds": round(seconds, 1),
            "chunks_per_second": round(encoded / seconds, 2) if seconds else None,
        }
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    vectors = np.load(folder / "vectors.npy", mmap_mode="r")
    offsets = np.load(folder / "offsets.npy")
    if len(offsets) != len(ids) + 1:
        raise ValueError(f"{folder} does not match the corpus; delete it and rebuild")
    return DocStore(ids, vectors, offsets), meta


def main(argv: list[str] | None = None) -> int:
    from retrieval.dense import load_chunks

    parser = argparse.ArgumentParser(description="Build the ColBERT document store")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--variant", default="raw", help="corpus variant: raw or contextual")
    args = parser.parse_args(argv)
    from retrieval.contextual import variant

    cfg = load_config()
    chunks, sha = load_chunks(variant(args.variant)[0])
    _, meta = build_store(cfg, chunks, sha, lambda c: ColBERTEncoder(c, device=args.device))
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
